from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, AsyncIterator
from urllib.parse import quote

import httpx
import websockets

PUMP_PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
PUMP_AMM_PROGRAM_ID = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
SOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
JUPITER_ORDER_URL = "https://api.jup.ag/swap/v2/order"
DEXSCREENER_BASE = "https://api.dexscreener.com"
GOPLUS_SOLANA_SECURITY_URL = "https://api.gopluslabs.io/api/v1/solana/token_security"
ZERO = Decimal("0")


class SolanaResearchError(RuntimeError):
    pass


def _d(value: Any, default: Decimal | None = ZERO) -> Decimal | None:
    if value in (None, ""):
        return default
    try:
        return Decimal(str(value))
    except (ValueError, TypeError, ArithmeticError):
        return default


def _keys(message: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for item in message.get("accountKeys", []) if isinstance(message.get("accountKeys"), list) else []:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict) and item.get("pubkey"):
            out.append(str(item["pubkey"]))
    return out


@dataclass(frozen=True)
class PumpLaunchEvent:
    signature: str
    slot: int
    creator: str
    mint: str
    program_id: str
    log_messages: tuple[str, ...]
    observed_at: datetime


@dataclass(frozen=True)
class JupiterShadowQuote:
    input_mint: str
    output_mint: str
    in_amount: int
    out_amount: int
    in_usd_value: Decimal | None
    out_usd_value: Decimal | None
    price_impact_pct: Decimal | None
    fee_bps: int | None
    fee_mint: str | None
    platform_fee_amount: int | None
    signature_fee_lamports: int | None
    prioritization_fee_lamports: int | None
    router: str | None
    mode: str | None
    request_id: str | None
    quote_time_ms: int | None
    transaction_present: bool
    captured_at: datetime


@dataclass(frozen=True)
class DexSnapshot:
    mint: str
    pair_address: str
    dex_id: str
    quote_symbol: str
    price_usd: Decimal
    liquidity_usd: Decimal
    market_cap: Decimal
    volume_5m: Decimal
    volume_1h: Decimal
    buys_5m: int
    sells_5m: int
    buys_1h: int
    sells_1h: int
    price_change_5m: Decimal
    price_change_1h: Decimal
    price_change_6h: Decimal
    price_change_24h: Decimal
    pair_created_at: datetime | None
    captured_at: datetime


@dataclass(frozen=True)
class SecuritySnapshot:
    mint: str
    mintable: bool | None
    freezable: bool | None
    non_transferable: bool | None
    metadata_mutable: bool | None
    malicious_creator: bool | None
    top10_holder_pct: Decimal | None
    transfer_fee_rate: Decimal | None
    trusted_token: bool | None
    raw: dict[str, Any]
    captured_at: datetime


class HeliusPumpStream:
    """Read-only Helius transactionSubscribe stream for Pump/PumpSwap activity."""

    def __init__(
        self,
        *,
        api_key: str,
        program_ids: list[str] | None = None,
        commitment: str = "confirmed",
        reconnect_max_seconds: float = 30.0,
    ) -> None:
        if not api_key:
            raise ValueError("HELIUS_API_KEY is required for the Solana launch stream")
        if commitment not in {"processed", "confirmed", "finalized"}:
            raise ValueError("invalid Solana commitment")
        self.url = f"wss://mainnet.helius-rpc.com/?api-key={quote(api_key)}"
        self.program_ids = program_ids or [PUMP_PROGRAM_ID, PUMP_AMM_PROGRAM_ID]
        self.commitment = commitment
        self.reconnect_max_seconds = reconnect_max_seconds

    def subscribe_message(self) -> str:
        return json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "transactionSubscribe",
                "params": [
                    {"failed": False, "vote": False, "accountInclude": self.program_ids},
                    {
                        "commitment": self.commitment,
                        "encoding": "jsonParsed",
                        "transactionDetails": "full",
                        "showRewards": False,
                        "maxSupportedTransactionVersion": 0,
                    },
                ],
            },
            separators=(",", ":"),
        )

    async def stream(self) -> AsyncIterator[dict[str, Any]]:
        delay = 1.0
        while True:
            try:
                async with websockets.connect(self.url, ping_interval=10, ping_timeout=20) as ws:
                    await ws.send(self.subscribe_message())
                    delay = 1.0
                    async for raw in ws:
                        try:
                            payload = json.loads(raw)
                        except (json.JSONDecodeError, TypeError):
                            continue
                        if payload.get("method") == "transactionNotification" and payload.get("params", {}).get("result"):
                            yield payload
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.reconnect_max_seconds)


def parse_pump_launch_notification(payload: dict[str, Any]) -> PumpLaunchEvent | None:
    """Parse the Helius-documented Pump launch pattern without guessing from price feeds."""
    result = payload.get("params", {}).get("result")
    if not isinstance(result, dict):
        return None
    wrapped = result.get("transaction")
    if not isinstance(wrapped, dict):
        return None
    meta = wrapped.get("meta")
    tx = wrapped.get("transaction")
    if not isinstance(meta, dict) or not isinstance(tx, dict):
        return None
    logs = tuple(str(x) for x in (meta.get("logMessages") or []))
    if not any("Instruction: InitializeMint2" in log for log in logs):
        return None
    message = tx.get("message")
    if not isinstance(message, dict):
        return None
    keys = _keys(message)
    if len(keys) < 2:
        return None
    program_id = PUMP_PROGRAM_ID if PUMP_PROGRAM_ID in keys or any(PUMP_PROGRAM_ID in log for log in logs) else ""
    if not program_id:
        return None
    signature = result.get("signature")
    slot = result.get("slot")
    if not signature or slot is None:
        return None
    return PumpLaunchEvent(
        signature=str(signature),
        slot=int(slot),
        creator=keys[0],
        mint=keys[1],
        program_id=program_id,
        log_messages=logs,
        observed_at=datetime.now(timezone.utc),
    )


class JupiterShadowClient:
    """Swap V2 `/order` price checks only. Taker is intentionally omitted; `/execute` is absent."""

    def __init__(self, *, api_key: str, timeout_seconds: float = 10.0, transport: httpx.AsyncBaseTransport | None = None) -> None:
        if not api_key:
            raise ValueError("JUPITER_API_KEY is required for shadow quotes")
        self.api_key = api_key
        self._http = httpx.AsyncClient(timeout=timeout_seconds, transport=transport)

    async def close(self) -> None:
        await self._http.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def order_quote(self, *, input_mint: str, output_mint: str, amount: int) -> JupiterShadowQuote:
        if amount <= 0:
            raise ValueError("amount must be positive")
        try:
            response = await self._http.get(
                JUPITER_ORDER_URL,
                params={"inputMint": input_mint, "outputMint": output_mint, "amount": str(amount)},
                headers={"x-api-key": self.api_key},
            )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SolanaResearchError(f"Jupiter shadow quote failed: {exc}") from exc
        transaction = data.get("transaction")
        if transaction:
            raise SolanaResearchError("Jupiter returned a transaction even though no taker was supplied")
        try:
            return JupiterShadowQuote(
                input_mint=str(data.get("inputMint", input_mint)),
                output_mint=str(data.get("outputMint", output_mint)),
                in_amount=int(data.get("inAmount", amount)),
                out_amount=int(data["outAmount"]),
                in_usd_value=_d(data.get("inUsdValue"), None),
                out_usd_value=_d(data.get("outUsdValue"), None),
                price_impact_pct=_d(data.get("priceImpactPct", data.get("priceImpact")), None),
                fee_bps=int(data["feeBps"]) if data.get("feeBps") is not None else None,
                fee_mint=str(data["feeMint"]) if data.get("feeMint") else None,
                platform_fee_amount=int(data.get("platformFee", {}).get("amount")) if isinstance(data.get("platformFee"), dict) and data["platformFee"].get("amount") is not None else None,
                signature_fee_lamports=int(data["signatureFeeLamports"]) if data.get("signatureFeeLamports") is not None else None,
                prioritization_fee_lamports=int(data["prioritizationFeeLamports"]) if data.get("prioritizationFeeLamports") is not None else None,
                router=str(data["router"]) if data.get("router") else None,
                mode=str(data["mode"]) if data.get("mode") else None,
                request_id=str(data["requestId"]) if data.get("requestId") else None,
                quote_time_ms=int(data["totalTime"]) if data.get("totalTime") is not None else None,
                transaction_present=False,
                captured_at=datetime.now(timezone.utc),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SolanaResearchError("Jupiter returned an incomplete quote") from exc


class DexScreenerClient:
    """Enrichment only; this client does not discover the Solana launch universe."""

    def __init__(self, *, timeout_seconds: float = 10.0, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._http = httpx.AsyncClient(base_url=DEXSCREENER_BASE, timeout=timeout_seconds, transport=transport)

    async def close(self) -> None:
        await self._http.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def token(self, mint: str) -> DexSnapshot | None:
        try:
            response = await self._http.get(f"/token-pairs/v1/solana/{mint}")
            response.raise_for_status()
            rows = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SolanaResearchError(f"DEX Screener enrichment failed: {exc}") from exc
        if not isinstance(rows, list):
            raise SolanaResearchError("unexpected DEX Screener response shape")
        pairs = [r for r in rows if isinstance(r, dict) and r.get("chainId") == "solana"]
        if not pairs:
            return None
        pair = max(pairs, key=lambda x: _d((x.get("liquidity") or {}).get("usd")) or ZERO)
        created = pair.get("pairCreatedAt")
        created_at = None
        if created:
            try:
                created_at = datetime.fromtimestamp(int(created) / 1000, tz=timezone.utc)
            except (ValueError, TypeError, OSError):
                pass
        tx5 = (pair.get("txns") or {}).get("m5") or {}
        tx1 = (pair.get("txns") or {}).get("h1") or {}
        vol = pair.get("volume") or {}
        change = pair.get("priceChange") or {}
        quote_token = pair.get("quoteToken") or {}
        return DexSnapshot(
            mint=mint,
            pair_address=str(pair.get("pairAddress", "")),
            dex_id=str(pair.get("dexId", "")),
            quote_symbol=str(quote_token.get("symbol", "")),
            price_usd=_d(pair.get("priceUsd")) or ZERO,
            liquidity_usd=_d((pair.get("liquidity") or {}).get("usd")) or ZERO,
            market_cap=_d(pair.get("marketCap", pair.get("fdv"))) or ZERO,
            volume_5m=_d(vol.get("m5")) or ZERO,
            volume_1h=_d(vol.get("h1")) or ZERO,
            buys_5m=int(tx5.get("buys", 0) or 0),
            sells_5m=int(tx5.get("sells", 0) or 0),
            buys_1h=int(tx1.get("buys", 0) or 0),
            sells_1h=int(tx1.get("sells", 0) or 0),
            price_change_5m=_d(change.get("m5")) or ZERO,
            price_change_1h=_d(change.get("h1")) or ZERO,
            price_change_6h=_d(change.get("h6")) or ZERO,
            price_change_24h=_d(change.get("h24")) or ZERO,
            pair_created_at=created_at,
            captured_at=datetime.now(timezone.utc),
        )


class GoPlusSolanaClient:
    def __init__(self, *, access_token: str = "", timeout_seconds: float = 10.0, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.access_token = access_token
        self._http = httpx.AsyncClient(timeout=timeout_seconds, transport=transport)

    async def close(self) -> None:
        await self._http.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def token_security(self, mint: str) -> SecuritySnapshot | None:
        headers = {"Authorization": f"Bearer {self.access_token}"} if self.access_token else {}
        try:
            response = await self._http.get(GOPLUS_SOLANA_SECURITY_URL, params={"contract_addresses": mint}, headers=headers)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SolanaResearchError(f"GoPlus Solana security lookup failed: {exc}") from exc
        result = data.get("result") if isinstance(data, dict) else None
        if not isinstance(result, dict):
            return None
        row = result.get(mint) or result.get(mint.lower())
        if not isinstance(row, dict):
            return None

        def status(name: str) -> bool | None:
            value = row.get(name)
            if isinstance(value, dict):
                value = value.get("status")
            if value in ("1", 1, True):
                return True
            if value in ("0", 0, False):
                return False
            return None

        holders = row.get("holders") if isinstance(row.get("holders"), list) else []
        top10 = sum((_d(h.get("percent")) or ZERO for h in holders[:10] if isinstance(h, dict)), ZERO) if holders else None
        creators = row.get("creator") if isinstance(row.get("creator"), list) else []
        malicious_creator = None
        if creators:
            flags = [c.get("malicious_address") for c in creators if isinstance(c, dict)]
            if flags:
                malicious_creator = any(v in ("1", 1, True) for v in flags)
        transfer_fee = row.get("transfer_fee") if isinstance(row.get("transfer_fee"), dict) else {}
        current_fee = transfer_fee.get("current_fee_rate") if isinstance(transfer_fee.get("current_fee_rate"), dict) else {}
        return SecuritySnapshot(
            mint=mint,
            mintable=status("mintable"),
            freezable=status("freezable"),
            non_transferable=True if row.get("non_transferable") in ("1", 1, True) else False if row.get("non_transferable") in ("0", 0, False) else None,
            metadata_mutable=status("metadata_mutable"),
            malicious_creator=malicious_creator,
            top10_holder_pct=top10,
            transfer_fee_rate=_d(current_fee.get("fee_rate"), None),
            trusted_token=True if row.get("trusted_token") in ("1", 1, True) else False if row.get("trusted_token") in ("0", 0, False) else None,
            raw=row,
            captured_at=datetime.now(timezone.utc),
        )
