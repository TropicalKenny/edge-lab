from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from urllib.parse import quote

import httpx

from app.venues.solana import SolanaResearchError


@dataclass(frozen=True)
class SolanaAssetMetadata:
    mint: str
    symbol: str | None
    name: str | None
    decimals: int
    supply_atomic: int | None
    token_program: str | None
    mint_authority: str | None
    freeze_authority: str | None
    mutable: bool | None
    cached_price_usd: Decimal | None
    captured_at: datetime


class HeliusAssetClient:
    """Read-only DAS metadata lookup. Helius price data is never used as the real-time execution price."""

    def __init__(self, *, api_key: str, timeout_seconds: float = 10.0, transport: httpx.AsyncBaseTransport | None = None) -> None:
        if not api_key:
            raise ValueError("HELIUS_API_KEY is required for asset metadata")
        self.url = f"https://mainnet.helius-rpc.com/?api-key={quote(api_key)}"
        self._http = httpx.AsyncClient(timeout=timeout_seconds, transport=transport)

    async def close(self) -> None:
        await self._http.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def get_asset(self, mint: str) -> SolanaAssetMetadata:
        payload = {
            "jsonrpc": "2.0",
            "id": "edge-lab",
            "method": "getAsset",
            "params": {"id": mint, "displayOptions": {"showFungible": True}},
        }
        try:
            response = await self._http.post(self.url, json=payload)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SolanaResearchError(f"Helius getAsset failed: {exc}") from exc
        result = data.get("result") if isinstance(data, dict) else None
        if not isinstance(result, dict):
            raise SolanaResearchError("Helius getAsset returned no asset")
        token_info = result.get("token_info") if isinstance(result.get("token_info"), dict) else {}
        content = result.get("content") if isinstance(result.get("content"), dict) else {}
        metadata = content.get("metadata") if isinstance(content.get("metadata"), dict) else {}
        price_info = token_info.get("price_info") if isinstance(token_info.get("price_info"), dict) else {}
        decimals = token_info.get("decimals")
        if decimals is None:
            raise SolanaResearchError("Helius asset metadata is missing token decimals")
        cached_price = price_info.get("price_per_token")
        return SolanaAssetMetadata(
            mint=mint,
            symbol=str(token_info.get("symbol") or metadata.get("symbol")) if token_info.get("symbol") or metadata.get("symbol") else None,
            name=str(metadata.get("name")) if metadata.get("name") else None,
            decimals=int(decimals),
            supply_atomic=int(token_info["supply"]) if token_info.get("supply") is not None else None,
            token_program=str(token_info["token_program"]) if token_info.get("token_program") else None,
            mint_authority=str(token_info["mint_authority"]) if token_info.get("mint_authority") else None,
            freeze_authority=str(token_info["freeze_authority"]) if token_info.get("freeze_authority") else None,
            mutable=bool(result["mutable"]) if result.get("mutable") is not None else None,
            cached_price_usd=Decimal(str(cached_price)) if cached_price is not None else None,
            captured_at=datetime.now(timezone.utc),
        )
