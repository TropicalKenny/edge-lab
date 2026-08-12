from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, AsyncIterator, Iterable

import httpx
import websockets

from app.schemas import BookLevel, PaperOrderRequest

MAINNET_INFO_URL = "https://api.hyperliquid.xyz/info"
TESTNET_INFO_URL = "https://api.hyperliquid-testnet.xyz/info"
MAINNET_WS_URL = "wss://api.hyperliquid.xyz/ws"
TESTNET_WS_URL = "wss://api.hyperliquid-testnet.xyz/ws"
ZERO = Decimal("0")
BPS = Decimal("10000")
HOURS_PER_YEAR = Decimal("8760")


def _d(value: Any, default: Decimal | None = ZERO) -> Decimal | None:
    if value is None:
        return default
    try:
        return Decimal(str(value))
    except (ValueError, TypeError, ArithmeticError):
        return default


def _utc_from_ms(ms: int | float | str) -> datetime:
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc)


@dataclass(frozen=True)
class PerpContext:
    coin: str
    sz_decimals: int
    max_leverage: int
    mark_px: Decimal
    mid_px: Decimal | None
    oracle_px: Decimal
    funding_rate_hourly: Decimal
    premium: Decimal | None
    open_interest: Decimal
    day_ntl_volume: Decimal
    captured_at: datetime


@dataclass(frozen=True)
class SpotContext:
    pair: str
    book_coin: str
    base: str
    quote: str
    mid_px: Decimal
    day_ntl_volume: Decimal
    captured_at: datetime


@dataclass(frozen=True)
class FundingRatePoint:
    coin: str
    funding_rate: Decimal
    premium: Decimal | None
    time: datetime


@dataclass(frozen=True)
class FundingCarryOpportunity:
    coin: str
    spot_pair: str
    direction: str
    perp_mark_px: Decimal
    spot_mid_px: Decimal
    funding_rate_hourly: Decimal
    simple_annualized_funding_pct: Decimal
    basis_bps: Decimal
    horizon_hours: int
    gross_funding_pct: Decimal
    estimated_cost_pct: Decimal
    expected_edge_pct: Decimal
    eligible: bool
    reasons: tuple[str, ...]
    captured_at: datetime


class HyperliquidInfoError(RuntimeError):
    pass


class HyperliquidInfoClient:
    """Read-only client for Hyperliquid's public `info` endpoint."""

    def __init__(
        self,
        *,
        network: str = "mainnet",
        timeout_seconds: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if network not in {"mainnet", "testnet"}:
            raise ValueError("network must be mainnet or testnet")
        self.network = network
        self.info_url = MAINNET_INFO_URL if network == "mainnet" else TESTNET_INFO_URL
        self.ws_url = MAINNET_WS_URL if network == "mainnet" else TESTNET_WS_URL
        self._http = httpx.AsyncClient(timeout=timeout_seconds, transport=transport)

    async def close(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "HyperliquidInfoClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def info(self, payload: dict[str, Any]) -> Any:
        try:
            response = await self._http.post(self.info_url, json=payload)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise HyperliquidInfoError(f"Hyperliquid info request failed: {exc}") from exc

    async def meta_and_asset_contexts(self, dex: str = "") -> Any:
        payload: dict[str, Any] = {"type": "metaAndAssetCtxs"}
        if dex:
            payload["dex"] = dex
        return await self.info(payload)

    async def spot_meta_and_asset_contexts(self) -> Any:
        return await self.info({"type": "spotMetaAndAssetCtxs"})

    async def funding_history(self, coin: str, start_time_ms: int, end_time_ms: int | None = None) -> Any:
        payload: dict[str, Any] = {"type": "fundingHistory", "coin": coin, "startTime": start_time_ms}
        if end_time_ms is not None:
            payload["endTime"] = end_time_ms
        return await self.info(payload)

    async def predicted_fundings(self) -> Any:
        return await self.info({"type": "predictedFundings"})

    async def l2_book(self, coin: str) -> Any:
        return await self.info({"type": "l2Book", "coin": coin})

    async def all_mids(self) -> Any:
        return await self.info({"type": "allMids"})


def parse_perp_contexts(payload: Any, *, captured_at: datetime | None = None) -> list[PerpContext]:
    captured_at = captured_at or datetime.now(timezone.utc)
    if not isinstance(payload, list) or len(payload) != 2:
        raise HyperliquidInfoError("unexpected metaAndAssetCtxs response shape")
    meta, contexts = payload
    universe = meta.get("universe", []) if isinstance(meta, dict) else []
    if not isinstance(contexts, list) or len(universe) != len(contexts):
        raise HyperliquidInfoError("perp metadata/context length mismatch")
    out: list[PerpContext] = []
    for asset, ctx in zip(universe, contexts, strict=True):
        mark = _d(ctx.get("markPx"), None)
        oracle = _d(ctx.get("oraclePx"), None)
        funding = _d(ctx.get("funding"), None)
        if mark is None or oracle is None or funding is None:
            continue
        out.append(
            PerpContext(
                coin=str(asset["name"]),
                sz_decimals=int(asset.get("szDecimals", 0)),
                max_leverage=int(asset.get("maxLeverage", 1)),
                mark_px=mark,
                mid_px=_d(ctx.get("midPx"), None),
                oracle_px=oracle,
                funding_rate_hourly=funding,
                premium=_d(ctx.get("premium"), None),
                open_interest=_d(ctx.get("openInterest")) or ZERO,
                day_ntl_volume=_d(ctx.get("dayNtlVlm")) or ZERO,
                captured_at=captured_at,
            )
        )
    return out


def parse_spot_contexts(payload: Any, *, captured_at: datetime | None = None) -> list[SpotContext]:
    captured_at = captured_at or datetime.now(timezone.utc)
    if not isinstance(payload, list) or len(payload) != 2:
        raise HyperliquidInfoError("unexpected spotMetaAndAssetCtxs response shape")
    meta, contexts = payload
    universe = meta.get("universe", []) if isinstance(meta, dict) else []
    tokens = meta.get("tokens", []) if isinstance(meta, dict) else []
    if not isinstance(contexts, list) or len(universe) != len(contexts):
        raise HyperliquidInfoError("spot metadata/context length mismatch")
    token_names = {int(t["index"]): str(t["name"]) for t in tokens if isinstance(t, dict) and "index" in t and "name" in t}
    out: list[SpotContext] = []
    for market, ctx in zip(universe, contexts, strict=True):
        book_coin = str(market.get("name", ""))
        token_ids = market.get("tokens", [])
        if not isinstance(token_ids, list) or len(token_ids) != 2:
            continue
        base = token_names.get(int(token_ids[0]))
        quote = token_names.get(int(token_ids[1]))
        if not base or not quote:
            continue
        pair = f"{base}/{quote}"
        mid = _d(ctx.get("midPx"), None) or _d(ctx.get("markPx"), None)
        if mid is None:
            continue
        out.append(
            SpotContext(
                pair=pair,
                book_coin=book_coin,
                base=base,
                quote=quote,
                mid_px=mid,
                day_ntl_volume=_d(ctx.get("dayNtlVlm")) or ZERO,
                captured_at=captured_at,
            )
        )
    return out


def parse_funding_history(payload: Any) -> list[FundingRatePoint]:
    if not isinstance(payload, list):
        raise HyperliquidInfoError("unexpected fundingHistory response shape")
    out: list[FundingRatePoint] = []
    for row in payload:
        try:
            out.append(
                FundingRatePoint(
                    coin=str(row["coin"]),
                    funding_rate=Decimal(str(row["fundingRate"])),
                    premium=_d(row.get("premium"), None),
                    time=_utc_from_ms(row["time"]),
                )
            )
        except (KeyError, ValueError, TypeError, ArithmeticError):
            continue
    return out


def l2_book_to_paper_order(
    payload: Any,
    *,
    side: str,
    quantity: Decimal,
    fee_bps: Decimal,
    allow_partial: bool = True,
    max_data_age_seconds: int = 5,
) -> PaperOrderRequest:
    if not isinstance(payload, dict) or not isinstance(payload.get("levels"), list) or len(payload["levels"]) != 2:
        raise HyperliquidInfoError("unexpected l2Book response shape")
    bids_raw, asks_raw = payload["levels"]
    bids = [BookLevel(price=Decimal(str(x["px"])), quantity=Decimal(str(x["sz"]))) for x in bids_raw]
    asks = [BookLevel(price=Decimal(str(x["px"])), quantity=Decimal(str(x["sz"]))) for x in asks_raw]
    return PaperOrderRequest(
        venue="hyperliquid",
        instrument=str(payload.get("coin", "unknown")),
        side=side,
        quantity=quantity,
        bids=bids,
        asks=asks,
        fee_bps=fee_bps,
        fixed_network_fee=ZERO,
        allow_partial=allow_partial,
        market_data_at=_utc_from_ms(payload["time"]),
        max_data_age_seconds=max_data_age_seconds,
    )


class FundingCarryAnalyzer:
    """Cost-aware, no-leverage research model for long-spot/short-perp carry."""

    def __init__(
        self,
        *,
        perp_taker_fee_bps: Decimal = Decimal("4.5"),
        spot_taker_fee_bps: Decimal = Decimal("7.0"),
        slippage_reserve_bps_per_leg: Decimal = Decimal("2.0"),
        spot_aliases: dict[str, str] | None = None,
    ) -> None:
        self.perp_taker_fee_bps = perp_taker_fee_bps
        self.spot_taker_fee_bps = spot_taker_fee_bps
        self.slippage_reserve_bps_per_leg = slippage_reserve_bps_per_leg
        self.spot_aliases = {"BTC": "UBTC", **(spot_aliases or {})}

    def analyze(
        self,
        perps: Iterable[PerpContext],
        spots: Iterable[SpotContext],
        *,
        horizon_hours: int = 24,
        min_expected_edge_pct: Decimal = ZERO,
    ) -> list[FundingCarryOpportunity]:
        if horizon_hours <= 0:
            raise ValueError("horizon_hours must be positive")
        spot_by_base = {s.base: s for s in spots if s.quote == "USDC"}
        out: list[FundingCarryOpportunity] = []
        for perp in perps:
            spot_base = self.spot_aliases.get(perp.coin, perp.coin)
            spot = spot_by_base.get(spot_base)
            if spot is None:
                continue
            reasons: list[str] = []
            funding = perp.funding_rate_hourly
            gross = funding * Decimal(horizon_hours)
            round_trip_fee_bps = Decimal("2") * (self.perp_taker_fee_bps + self.spot_taker_fee_bps)
            slippage_bps = Decimal("4") * self.slippage_reserve_bps_per_leg
            cost_pct = (round_trip_fee_bps + slippage_bps) / BPS
            edge = gross - cost_pct
            basis_bps = ((perp.mark_px - spot.mid_px) / spot.mid_px) * BPS
            if funding <= ZERO:
                reasons.append("NON_POSITIVE_FUNDING")
            if spot.day_ntl_volume <= ZERO or perp.day_ntl_volume <= ZERO:
                reasons.append("NO_RECORDED_DAY_VOLUME")
            if edge <= min_expected_edge_pct:
                reasons.append("EDGE_BELOW_THRESHOLD")
            out.append(
                FundingCarryOpportunity(
                    coin=perp.coin,
                    spot_pair=spot.pair,
                    direction="long_spot_short_perp",
                    perp_mark_px=perp.mark_px,
                    spot_mid_px=spot.mid_px,
                    funding_rate_hourly=funding,
                    simple_annualized_funding_pct=funding * HOURS_PER_YEAR,
                    basis_bps=basis_bps,
                    horizon_hours=horizon_hours,
                    gross_funding_pct=gross,
                    estimated_cost_pct=cost_pct,
                    expected_edge_pct=edge,
                    eligible=not reasons,
                    reasons=tuple(reasons),
                    captured_at=max(perp.captured_at, spot.captured_at),
                )
            )
        return sorted(out, key=lambda x: x.expected_edge_pct, reverse=True)


def subscription_message(subscription: dict[str, Any]) -> str:
    return json.dumps({"method": "subscribe", "subscription": subscription}, separators=(",", ":"))


class HyperliquidWebSocket:
    """Read-only reconnecting public WebSocket stream."""

    def __init__(self, *, network: str = "mainnet", reconnect_max_seconds: float = 30.0) -> None:
        if network not in {"mainnet", "testnet"}:
            raise ValueError("network must be mainnet or testnet")
        self.url = MAINNET_WS_URL if network == "mainnet" else TESTNET_WS_URL
        self.reconnect_max_seconds = reconnect_max_seconds

    async def stream(self, subscriptions: list[dict[str, Any]]) -> AsyncIterator[dict[str, Any]]:
        delay = 1.0
        while True:
            try:
                async with websockets.connect(self.url, ping_interval=20, ping_timeout=20) as ws:
                    for sub in subscriptions:
                        await ws.send(subscription_message(sub))
                    delay = 1.0
                    async for raw in ws:
                        try:
                            yield json.loads(raw)
                        except (json.JSONDecodeError, TypeError):
                            continue
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.reconnect_max_seconds)
