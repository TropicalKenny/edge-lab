from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import httpx
import websockets

from app.venues.solana import (
    PUMP_AMM_PROGRAM_ID,
    PUMP_PROGRAM_ID,
    SolanaResearchError,
)
from app.venues.solana_asset import SolanaAssetMetadata


class SolanaRpcClient:
    """Read-only standard Solana JSON-RPC client.

    This deliberately exposes only the methods Edge Lab needs for research.
    It has no transaction-signing or sendTransaction path.
    """

    def __init__(
        self,
        *,
        http_url: str,
        timeout_seconds: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not http_url.strip():
            raise ValueError("SOLANA_RPC_HTTP_URL is required")
        self.http_url = http_url.strip()
        self._http = httpx.AsyncClient(timeout=timeout_seconds, transport=transport)
        self._request_id = 0

    async def close(self) -> None:
        await self._http.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def call(self, method: str, params: list[Any]) -> Any:
        if method in {"sendTransaction", "simulateTransaction", "requestAirdrop"}:
            raise SolanaResearchError(f"forbidden Solana RPC method: {method}")
        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }
        try:
            response = await self._http.post(self.http_url, json=payload)
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SolanaResearchError(f"Solana RPC {method} failed: {exc}") from exc
        if not isinstance(body, dict):
            raise SolanaResearchError(f"Solana RPC {method} returned invalid JSON-RPC body")
        if body.get("error"):
            raise SolanaResearchError(f"Solana RPC {method} returned error: {str(body['error'])[:300]}")
        return body.get("result")

    async def get_transaction(self, signature: str, *, commitment: str) -> dict[str, Any] | None:
        result = await self.call(
            "getTransaction",
            [
                signature,
                {
                    "commitment": commitment,
                    "encoding": "jsonParsed",
                    "maxSupportedTransactionVersion": 0,
                },
            ],
        )
        return result if isinstance(result, dict) else None

    async def get_mint_metadata(self, mint: str, *, commitment: str = "confirmed") -> SolanaAssetMetadata:
        result = await self.call(
            "getAccountInfo",
            [mint, {"commitment": commitment, "encoding": "jsonParsed"}],
        )
        if not isinstance(result, dict):
            raise SolanaResearchError("Solana getAccountInfo returned no result")
        value = result.get("value")
        if not isinstance(value, dict):
            raise SolanaResearchError("Solana getAccountInfo returned no mint account")
        data = value.get("data")
        parsed = data.get("parsed") if isinstance(data, dict) else None
        info = parsed.get("info") if isinstance(parsed, dict) else None
        if not isinstance(info, dict):
            raise SolanaResearchError("Solana mint account is not jsonParsed")
        decimals = info.get("decimals")
        if decimals is None:
            raise SolanaResearchError("Solana mint metadata is missing decimals")
        supply = info.get("supply")
        return SolanaAssetMetadata(
            mint=mint,
            symbol=None,
            name=None,
            decimals=int(decimals),
            supply_atomic=int(supply) if supply is not None else None,
            token_program=str(value.get("owner")) if value.get("owner") else None,
            mint_authority=str(info.get("mintAuthority")) if info.get("mintAuthority") else None,
            freeze_authority=str(info.get("freezeAuthority")) if info.get("freezeAuthority") else None,
            mutable=None,
            cached_price_usd=None,
            captured_at=datetime.now(timezone.utc),
        )


class SolanaRpcAssetClient:
    """Provider-neutral mint metadata lookup over standard Solana JSON-RPC."""

    def __init__(
        self,
        *,
        http_url: str,
        commitment: str = "confirmed",
        timeout_seconds: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if commitment not in {"processed", "confirmed", "finalized"}:
            raise ValueError("invalid Solana commitment")
        self.commitment = commitment
        self._rpc = SolanaRpcClient(
            http_url=http_url,
            timeout_seconds=timeout_seconds,
            transport=transport,
        )

    async def __aenter__(self):
        await self._rpc.__aenter__()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._rpc.close()

    async def get_asset(self, mint: str) -> SolanaAssetMetadata:
        return await self._rpc.get_mint_metadata(mint, commitment=self.commitment)


class SolanaRpcPumpStream:
    """Provider-neutral Pump/PumpSwap launch stream using standard Solana RPC.

    The WebSocket side uses logsSubscribe, then the HTTP endpoint fetches the
    matching transaction only for candidate mint-initialization logs. This is
    intentionally read-only and compatible with standard Solana RPC vendors
    such as Alchemy.
    """

    def __init__(
        self,
        *,
        http_url: str,
        ws_url: str,
        program_ids: list[str] | None = None,
        commitment: str = "confirmed",
        timeout_seconds: float = 10.0,
        reconnect_max_seconds: float = 30.0,
    ) -> None:
        if not http_url.strip() or not ws_url.strip():
            raise ValueError("SOLANA_RPC_HTTP_URL and SOLANA_RPC_WS_URL are required")
        if commitment not in {"processed", "confirmed", "finalized"}:
            raise ValueError("invalid Solana commitment")
        self.http_url = http_url.strip()
        self.ws_url = ws_url.strip()
        self.program_ids = program_ids or [PUMP_PROGRAM_ID, PUMP_AMM_PROGRAM_ID]
        self.commitment = commitment
        self.timeout_seconds = timeout_seconds
        self.reconnect_max_seconds = reconnect_max_seconds

    def subscribe_messages(self) -> list[str]:
        messages: list[str] = []
        for index, program_id in enumerate(self.program_ids, start=1):
            messages.append(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": index,
                        "method": "logsSubscribe",
                        "params": [
                            {"mentions": [program_id]},
                            {"commitment": self.commitment},
                        ],
                    },
                    separators=(",", ":"),
                )
            )
        return messages

    async def _fetch_transaction(self, rpc: SolanaRpcClient, signature: str) -> dict[str, Any] | None:
        for attempt in range(3):
            tx = await rpc.get_transaction(signature, commitment=self.commitment)
            if tx is not None:
                return tx
            await asyncio.sleep(0.25 * (attempt + 1))
        return None

    @staticmethod
    def _candidate(value: dict[str, Any]) -> bool:
        if value.get("err") is not None:
            return False
        logs = value.get("logs")
        if not isinstance(logs, list):
            return False
        return any("Instruction: InitializeMint2" in str(log) for log in logs)

    @staticmethod
    def _normalize_notification(signature: str, slot: int, tx: dict[str, Any]) -> dict[str, Any] | None:
        meta = tx.get("meta")
        transaction = tx.get("transaction")
        if not isinstance(meta, dict) or not isinstance(transaction, dict):
            return None
        return {
            "method": "transactionNotification",
            "params": {
                "result": {
                    "signature": signature,
                    "slot": int(tx.get("slot", slot)),
                    "transaction": {
                        "meta": meta,
                        "transaction": transaction,
                    },
                }
            },
        }

    async def stream(self) -> AsyncIterator[dict[str, Any]]:
        delay = 1.0
        async with SolanaRpcClient(http_url=self.http_url, timeout_seconds=self.timeout_seconds) as rpc:
            while True:
                try:
                    async with websockets.connect(self.ws_url, ping_interval=10, ping_timeout=20) as ws:
                        for message in self.subscribe_messages():
                            await ws.send(message)
                        delay = 1.0
                        async for raw in ws:
                            try:
                                payload = json.loads(raw)
                            except (json.JSONDecodeError, TypeError):
                                continue
                            if payload.get("method") != "logsNotification":
                                continue
                            result = payload.get("params", {}).get("result")
                            if not isinstance(result, dict):
                                continue
                            value = result.get("value")
                            context = result.get("context")
                            if not isinstance(value, dict) or not isinstance(context, dict):
                                continue
                            if not self._candidate(value):
                                continue
                            signature = value.get("signature")
                            slot = context.get("slot")
                            if not signature or slot is None:
                                continue
                            try:
                                tx = await self._fetch_transaction(rpc, str(signature))
                            except SolanaResearchError:
                                continue
                            if tx is None:
                                continue
                            normalized = self._normalize_notification(str(signature), int(slot), tx)
                            if normalized is not None:
                                yield normalized
                except asyncio.CancelledError:
                    raise
                except Exception:
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, self.reconnect_max_seconds)
