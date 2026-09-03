from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, AsyncIterator, Iterable

import httpx
import websockets

GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"
GEOBLOCK_URL = "https://polymarket.com/api/geoblock"
MARKET_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
ZERO = Decimal("0")
ONE = Decimal("1")
BPS = Decimal("10000")
FEE_QUANT = Decimal("0.00001")


class PolymarketPublicError(RuntimeError):
    pass


def _d(value: Any, default: Decimal | None = None) -> Decimal | None:
    if value is None or value == "":
        return default
    try:
        return Decimal(str(value))
    except (ValueError, TypeError, ArithmeticError):
        return default


def _bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes"}
    if value is None:
        return default
    return bool(value)


def _listish(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        if isinstance(value, (int, float, Decimal)) or (isinstance(value, str) and value.isdigit()):
            raw = int(value)
            if raw > 10_000_000_000:
                raw /= 1000
            return datetime.fromtimestamp(raw, tz=timezone.utc)
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError, OSError, OverflowError):
        return None


@dataclass(frozen=True)
class FeeSchedule:
    rate: Decimal
    exponent: int
    taker_only: bool
    rebate_rate: Decimal = ZERO


@dataclass(frozen=True)
class MarketContext:
    market_id: str
    condition_id: str
    question: str
    slug: str
    event_id: str | None
    event_slug: str | None
    event_title: str | None
    yes_token_id: str | None
    no_token_id: str | None
    outcome_labels: tuple[str, ...]
    active: bool
    closed: bool
    accepting_orders: bool
    enable_order_book: bool
    neg_risk: bool
    neg_risk_other: bool
    fees_enabled: bool
    fee_schedule: FeeSchedule | None
    resolution_source: str | None
    description: str | None
    group_item_title: str | None
    end_date: datetime | None
    captured_at: datetime

    @property
    def is_tradeable_binary(self) -> bool:
        return (
            self.active
            and not self.closed
            and self.accepting_orders
            and self.enable_order_book
            and bool(self.yes_token_id)
            and bool(self.no_token_id)
        )


@dataclass(frozen=True)
class EventContext:
    event_id: str
    title: str
    slug: str
    description: str | None
    resolution_source: str | None
    neg_risk: bool
    neg_risk_augmented: bool
    markets: tuple[MarketContext, ...]
    captured_at: datetime


@dataclass(frozen=True)
class PriceLevel:
    price: Decimal
    size: Decimal


@dataclass(frozen=True)
class OrderBook:
    condition_id: str
    token_id: str
    bids: tuple[PriceLevel, ...]
    asks: tuple[PriceLevel, ...]
    min_order_size: Decimal
    tick_size: Decimal
    neg_risk: bool
    last_trade_price: Decimal | None
    book_hash: str | None
    timestamp: datetime
    captured_at: datetime


@dataclass(frozen=True)
class LegExecution:
    market_id: str
    condition_id: str
    token_id: str
    outcome: str
    shares: Decimal
    average_price: Decimal
    notional: Decimal
    fee: Decimal
    total_cost: Decimal


@dataclass(frozen=True)
class StructuralOpportunity:
    kind: str
    event_id: str | None
    condition_id: str | None
    quantity: Decimal
    gross_cost: Decimal
    total_fees: Decimal
    total_cost: Decimal
    payout: Decimal
    net_profit: Decimal
    roi_bps: Decimal
    eligible: bool
    reasons: tuple[str, ...]
    legs: tuple[LegExecution, ...]
    captured_at: datetime


@dataclass(frozen=True)
class StructuralScanResult:
    opportunities: tuple[StructuralOpportunity, ...]
    rejection_counts: dict[str, int]


class PolymarketPublicClient:
    """Public-only Gamma/CLOB client. It deliberately exposes no authenticated trading methods."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 10.0,
        gamma_transport: httpx.AsyncBaseTransport | None = None,
        clob_transport: httpx.AsyncBaseTransport | None = None,
        web_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._gamma = httpx.AsyncClient(base_url=GAMMA_BASE, timeout=timeout_seconds, transport=gamma_transport)
        self._clob = httpx.AsyncClient(base_url=CLOB_BASE, timeout=timeout_seconds, transport=clob_transport)
        self._web = httpx.AsyncClient(timeout=timeout_seconds, transport=web_transport)

    async def close(self) -> None:
        await asyncio.gather(self._gamma.aclose(), self._clob.aclose(), self._web.aclose())

    async def __aenter__(self) -> "PolymarketPublicClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    @staticmethod
    async def _json(response: httpx.Response, label: str) -> Any:
        try:
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise PolymarketPublicError(f"{label} request failed: {exc}") from exc

    async def list_markets_page(
        self,
        *,
        limit: int = 100,
        after_cursor: str | None = None,
        closed: bool = False,
    ) -> dict[str, Any]:
        if limit < 1 or limit > 100:
            raise ValueError("Polymarket keyset page limit must be between 1 and 100")
        params: dict[str, Any] = {
            "limit": limit,
            "closed": str(closed).lower(),
            "order": "liquidityNum",
            "ascending": "false",
        }
        if after_cursor:
            params["after_cursor"] = after_cursor
        return await self._json(await self._gamma.get("/markets/keyset", params=params), "Gamma markets")

    async def get_event(self, event_id: str) -> dict[str, Any]:
        return await self._json(await self._gamma.get(f"/events/{event_id}"), "Gamma event")

    async def get_clob_market_info(self, condition_id: str) -> dict[str, Any]:
        return await self._json(await self._clob.get(f"/clob-markets/{condition_id}"), "CLOB market info")

    async def get_book(self, token_id: str) -> dict[str, Any]:
        return await self._json(await self._clob.get("/book", params={"token_id": token_id}), "CLOB book")

    async def get_books(self, token_ids: list[str]) -> list[dict[str, Any]]:
        if not token_ids:
            return []
        if len(token_ids) > 100:
            raise ValueError("batch book request is capped locally at 100 token IDs")
        body = [{"token_id": token_id} for token_id in token_ids]
        data = await self._json(await self._clob.post("/books", json=body), "CLOB books")
        if not isinstance(data, list):
            raise PolymarketPublicError("unexpected CLOB books response shape")
        return data

    async def geoblock(self) -> dict[str, Any]:
        data = await self._json(await self._web.get(GEOBLOCK_URL), "geoblock")
        if not isinstance(data, dict) or "blocked" not in data:
            raise PolymarketPublicError("unexpected geoblock response shape")
        return data


def parse_fee_schedule(row: dict[str, Any]) -> FeeSchedule | None:
    enabled = row.get("feesEnabled", row.get("fees_enabled"))
    schedule = row.get("feeSchedule", row.get("fee_schedule"))
    if enabled is False:
        return FeeSchedule(rate=ZERO, exponent=1, taker_only=True, rebate_rate=ZERO)
    if not isinstance(schedule, dict):
        return None
    rate = _d(schedule.get("rate"), None)
    exponent_raw = _d(schedule.get("exponent"), None)
    rebate = _d(schedule.get("rebateRate", schedule.get("rebate_rate")), ZERO) or ZERO
    if rate is None or exponent_raw is None or rate < ZERO or rate > ONE:
        return None
    if exponent_raw != exponent_raw.to_integral_value() or exponent_raw < ZERO or exponent_raw > Decimal("8"):
        return None
    return FeeSchedule(
        rate=rate,
        exponent=int(exponent_raw),
        taker_only=_bool(schedule.get("takerOnly", schedule.get("taker_only")), True),
        rebate_rate=rebate,
    )


def parse_market(row: dict[str, Any], *, event_fallback: dict[str, Any] | None = None, captured_at: datetime | None = None) -> MarketContext:
    captured_at = captured_at or datetime.now(timezone.utc)
    event_rows = row.get("events") if isinstance(row.get("events"), list) else []
    event = event_rows[0] if event_rows and isinstance(event_rows[0], dict) else (event_fallback or {})
    outcomes = tuple(str(x) for x in _listish(row.get("outcomes")))
    token_ids = [str(x) for x in _listish(row.get("clobTokenIds", row.get("clob_token_ids")))]
    yes_token = no_token = None
    if len(token_ids) == 2:
        if len(outcomes) == 2:
            for label, token_id in zip(outcomes, token_ids, strict=True):
                if label.lower() == "yes":
                    yes_token = token_id
                elif label.lower() == "no":
                    no_token = token_id
        if yes_token is None and no_token is None and not outcomes:
            yes_token, no_token = token_ids
    condition_id = str(row.get("conditionId", row.get("condition_id", "")))
    if not condition_id:
        raise PolymarketPublicError("market missing condition ID")
    return MarketContext(
        market_id=str(row.get("id", condition_id)),
        condition_id=condition_id,
        question=str(row.get("question", "")),
        slug=str(row.get("slug", "")),
        event_id=str(event.get("id")) if event.get("id") is not None else None,
        event_slug=str(event.get("slug")) if event.get("slug") else None,
        event_title=str(event.get("title")) if event.get("title") else None,
        yes_token_id=yes_token,
        no_token_id=no_token,
        outcome_labels=outcomes,
        active=_bool(row.get("active"), False),
        closed=_bool(row.get("closed"), False),
        accepting_orders=_bool(row.get("acceptingOrders", row.get("accepting_orders")), False),
        enable_order_book=_bool(row.get("enableOrderBook", row.get("enable_order_book")), False),
        neg_risk=_bool(row.get("negRisk", row.get("neg_risk", event.get("negRisk"))), False),
        neg_risk_other=_bool(row.get("negRiskOther", row.get("neg_risk_other")), False),
        fees_enabled=_bool(row.get("feesEnabled", row.get("fees_enabled")), False),
        fee_schedule=parse_fee_schedule(row),
        resolution_source=str(row.get("resolutionSource", event.get("resolutionSource"))) if row.get("resolutionSource", event.get("resolutionSource")) else None,
        description=str(row.get("description")) if row.get("description") else None,
        group_item_title=str(row.get("groupItemTitle", row.get("group_item_title"))) if row.get("groupItemTitle", row.get("group_item_title")) else None,
        end_date=_dt(row.get("endDate", row.get("end_date"))),
        captured_at=captured_at,
    )


def parse_event(row: dict[str, Any], *, captured_at: datetime | None = None) -> EventContext:
    captured_at = captured_at or datetime.now(timezone.utc)
    event_id = str(row.get("id", ""))
    if not event_id:
        raise PolymarketPublicError("event missing ID")
    markets: list[MarketContext] = []
    for market_row in row.get("markets", []) if isinstance(row.get("markets"), list) else []:
        if not isinstance(market_row, dict):
            continue
        try:
            markets.append(parse_market(market_row, event_fallback=row, captured_at=captured_at))
        except PolymarketPublicError:
            continue
    return EventContext(
        event_id=event_id,
        title=str(row.get("title", "")),
        slug=str(row.get("slug", "")),
        description=str(row.get("description")) if row.get("description") else None,
        resolution_source=str(row.get("resolutionSource")) if row.get("resolutionSource") else None,
        neg_risk=_bool(row.get("negRisk"), False),
        neg_risk_augmented=_bool(row.get("negRiskAugmented"), False),
        markets=tuple(markets),
        captured_at=captured_at,
    )


def parse_book(row: dict[str, Any], *, captured_at: datetime | None = None) -> OrderBook:
    captured_at = captured_at or datetime.now(timezone.utc)
    token_id = str(row.get("asset_id", row.get("assetId", "")))
    if not token_id:
        raise PolymarketPublicError("order book missing asset ID")
    timestamp = _dt(row.get("timestamp"))
    if timestamp is None:
        raise PolymarketPublicError("order book missing valid timestamp")
    def levels(key: str, reverse: bool) -> tuple[PriceLevel, ...]:
        parsed: list[PriceLevel] = []
        for level in row.get(key, []) if isinstance(row.get(key), list) else []:
            if not isinstance(level, dict):
                continue
            price = _d(level.get("price"), None)
            size = _d(level.get("size"), None)
            if price is None or size is None or price <= ZERO or price >= ONE or size <= ZERO:
                continue
            parsed.append(PriceLevel(price=price, size=size))
        return tuple(sorted(parsed, key=lambda x: x.price, reverse=reverse))
    min_order = _d(row.get("min_order_size"), None)
    tick = _d(row.get("tick_size"), None)
    if min_order is None or min_order <= ZERO or tick is None or tick <= ZERO:
        raise PolymarketPublicError("order book missing valid min order size/tick size")
    return OrderBook(
        condition_id=str(row.get("market", "")),
        token_id=token_id,
        bids=levels("bids", True),
        asks=levels("asks", False),
        min_order_size=min_order,
        tick_size=tick,
        neg_risk=_bool(row.get("neg_risk"), False),
        last_trade_price=_d(row.get("last_trade_price"), None),
        book_hash=str(row.get("hash")) if row.get("hash") else None,
        timestamp=timestamp,
        captured_at=captured_at,
    )


def taker_fee(shares: Decimal, price: Decimal, schedule: FeeSchedule, *, buffer_pct: Decimal = ZERO) -> Decimal:
    if shares <= ZERO or schedule.rate <= ZERO:
        return ZERO
    if price <= ZERO or price >= ONE:
        raise ValueError("prediction-market price must be between 0 and 1")
    curve = (price * (ONE - price)) ** schedule.exponent
    raw = shares * schedule.rate * curve * (ONE + buffer_pct / Decimal("100"))
    return raw.quantize(FEE_QUANT, rounding=ROUND_HALF_UP)


def walk_buy(
    *,
    market: MarketContext,
    book: OrderBook,
    outcome: str,
    quantity: Decimal,
    fee_buffer_pct: Decimal = ZERO,
) -> LegExecution | None:
    if quantity <= ZERO or quantity < book.min_order_size or not book.asks:
        return None
    if market.fee_schedule is None:
        return None
    remaining = quantity
    notional = fees = ZERO
    for level in book.asks:
        if remaining <= ZERO:
            break
        take = min(remaining, level.size)
        notional += take * level.price
        fees += taker_fee(take, level.price, market.fee_schedule, buffer_pct=fee_buffer_pct)
        remaining -= take
    if remaining > ZERO:
        return None
    return LegExecution(
        market_id=market.market_id,
        condition_id=market.condition_id,
        token_id=book.token_id,
        outcome=outcome,
        shares=quantity,
        average_price=notional / quantity,
        notional=notional,
        fee=fees,
        total_cost=notional + fees,
    )


def _candidate_quantities(books: Iterable[OrderBook], max_shares: Decimal) -> list[Decimal]:
    books = list(books)
    if not books or max_shares <= ZERO or any(not b.asks for b in books):
        return []
    max_common = min(sum((x.size for x in b.asks), ZERO) for b in books)
    max_common = min(max_common, max_shares)
    minimum = max(b.min_order_size for b in books)
    if max_common < minimum:
        return []
    candidates = {max_common, minimum}
    for book in books:
        cumulative = ZERO
        for level in book.asks:
            cumulative += level.size
            clipped = min(cumulative, max_common)
            if clipped >= minimum:
                candidates.add(clipped)
            if cumulative >= max_common:
                break
    return sorted(q for q in candidates if minimum <= q <= max_common)


class StructuralArbitrageAnalyzer:
    def __init__(
        self,
        *,
        min_edge_bps: Decimal = Decimal("10"),
        max_shares: Decimal = Decimal("100"),
        max_book_age_seconds: int = 10,
        fee_buffer_pct: Decimal = Decimal("2"),
    ) -> None:
        self.min_edge_bps = min_edge_bps
        self.max_shares = max_shares
        self.max_book_age_seconds = max_book_age_seconds
        self.fee_buffer_pct = fee_buffer_pct

    def _book_problem(self, book: OrderBook, *, now: datetime) -> str | None:
        age = (now - book.timestamp).total_seconds()
        if age < -1 or age > self.max_book_age_seconds:
            return "STALE_BOOK"
        if not book.asks:
            return "NO_ASK_LIQUIDITY"
        return None

    def _best_basket(
        self,
        *,
        kind: str,
        legs: list[tuple[MarketContext, OrderBook, str]],
        payout_per_share: Decimal,
        event_id: str | None,
        condition_id: str | None,
        blockers: tuple[str, ...] = (),
        now: datetime | None = None,
    ) -> tuple[StructuralOpportunity | None, tuple[str, ...]]:
        now = now or datetime.now(timezone.utc)
        if not legs:
            return None, ("NO_LEGS",)
        for market, book, _ in legs:
            if market.fee_schedule is None:
                return None, ("UNKNOWN_FEE_SCHEDULE",)
            problem = self._book_problem(book, now=now)
            if problem:
                return None, (problem,)
        best: StructuralOpportunity | None = None
        for quantity in _candidate_quantities((book for _, book, _ in legs), self.max_shares):
            executions: list[LegExecution] = []
            for market, book, outcome in legs:
                execution = walk_buy(
                    market=market,
                    book=book,
                    outcome=outcome,
                    quantity=quantity,
                    fee_buffer_pct=self.fee_buffer_pct,
                )
                if execution is None:
                    executions = []
                    break
                executions.append(execution)
            if not executions:
                continue
            gross = sum((x.notional for x in executions), ZERO)
            fees = sum((x.fee for x in executions), ZERO)
            total = gross + fees
            payout = payout_per_share * quantity
            profit = payout - total
            roi_bps = (profit / total) * BPS if total > ZERO else ZERO
            if profit <= ZERO or roi_bps < self.min_edge_bps:
                continue
            reasons = tuple(blockers)
            candidate = StructuralOpportunity(
                kind=kind,
                event_id=event_id,
                condition_id=condition_id,
                quantity=quantity,
                gross_cost=gross,
                total_fees=fees,
                total_cost=total,
                payout=payout,
                net_profit=profit,
                roi_bps=roi_bps,
                eligible=not reasons,
                reasons=reasons,
                legs=tuple(executions),
                captured_at=max(book.timestamp for _, book, _ in legs),
            )
            if best is None or candidate.net_profit > best.net_profit:
                best = candidate
        return (best, ()) if best else (None, ("NO_EXECUTABLE_EDGE",))

    def binary_complete_set(
        self,
        market: MarketContext,
        books: dict[str, OrderBook],
        *,
        now: datetime | None = None,
    ) -> tuple[StructuralOpportunity | None, tuple[str, ...]]:
        if not market.is_tradeable_binary:
            return None, ("MARKET_NOT_TRADEABLE_BINARY",)
        if market.fees_enabled and market.fee_schedule is None:
            return None, ("UNKNOWN_FEE_SCHEDULE",)
        yes = books.get(market.yes_token_id or "")
        no = books.get(market.no_token_id or "")
        if yes is None or no is None:
            return None, ("MISSING_BOOK",)
        return self._best_basket(
            kind="binary_complete_set",
            legs=[(market, yes, "Yes"), (market, no, "No")],
            payout_per_share=ONE,
            event_id=market.event_id,
            condition_id=market.condition_id,
            now=now,
        )

    def neg_risk_event(
        self,
        event: EventContext,
        books: dict[str, OrderBook],
        *,
        now: datetime | None = None,
    ) -> tuple[list[StructuralOpportunity], dict[str, int]]:
        rejected: dict[str, int] = {}
        if not event.neg_risk:
            return [], {"NOT_NEG_RISK": 1}
        if event.neg_risk_augmented:
            return [], {"AUGMENTED_NEG_RISK_DEFERRED": 1}
        markets = [m for m in event.markets if m.is_tradeable_binary]
        if len(markets) < 3:
            return [], {"INCOMPLETE_NEG_RISK_EVENT": 1}
        if any(m.fees_enabled and m.fee_schedule is None for m in markets):
            return [], {"UNKNOWN_FEE_SCHEDULE": 1}
        if any((m.yes_token_id or "") not in books or (m.no_token_id or "") not in books for m in markets):
            return [], {"MISSING_BOOK": 1}
        unsafe_other = any(
            m.neg_risk_other or (m.group_item_title and m.group_item_title.strip().lower() == "other")
            for m in markets
        )
        blockers = ("DYNAMIC_OTHER_OUTCOME",) if unsafe_other else ()
        yes_legs = [(m, books[m.yes_token_id or ""], "Yes") for m in markets]
        no_legs = [(m, books[m.no_token_id or ""], "No") for m in markets]
        opportunities: list[StructuralOpportunity] = []
        yes_op, yes_reasons = self._best_basket(
            kind="negrisk_yes_complete_set",
            legs=yes_legs,
            payout_per_share=ONE,
            event_id=event.event_id,
            condition_id=None,
            blockers=blockers,
            now=now,
        )
        no_op, no_reasons = self._best_basket(
            kind="negrisk_no_complete_set",
            legs=no_legs,
            payout_per_share=Decimal(len(markets) - 1),
            event_id=event.event_id,
            condition_id=None,
            blockers=blockers,
            now=now,
        )
        for op in (yes_op, no_op):
            if op is not None:
                opportunities.append(op)
        for reason in (*yes_reasons, *no_reasons):
            rejected[reason] = rejected.get(reason, 0) + 1
        return opportunities, rejected


class PolymarketMarketWebSocket:
    """Public market-data WebSocket. No user/authenticated channel is implemented."""

    def __init__(self, *, reconnect_max_seconds: float = 30.0) -> None:
        self.reconnect_max_seconds = reconnect_max_seconds

    async def stream(self, asset_ids: list[str]) -> AsyncIterator[dict[str, Any]]:
        if not asset_ids:
            raise ValueError("at least one asset ID is required")
        delay = 1.0
        subscription = json.dumps(
            {"assets_ids": asset_ids, "type": "market", "custom_feature_enabled": True},
            separators=(",", ":"),
        )
        while True:
            try:
                async with websockets.connect(MARKET_WS_URL, ping_interval=20, ping_timeout=20) as ws:
                    await ws.send(subscription)
                    delay = 1.0
                    async for raw in ws:
                        try:
                            message = json.loads(raw)
                        except (json.JSONDecodeError, TypeError):
                            continue
                        if isinstance(message, dict):
                            yield message
                        elif isinstance(message, list):
                            for item in message:
                                if isinstance(item, dict):
                                    yield item
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.reconnect_max_seconds)
