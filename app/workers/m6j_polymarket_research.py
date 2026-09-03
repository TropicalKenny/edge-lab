from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal

import websockets
from sqlalchemy import select

from app.config import get_settings
from app.database import get_session_factory
from app.forward_models import ForwardStudy
from app.polymarket_research import PolymarketResearchService
from app.research_acceleration import polymarket_book_from_ws
from app.scan_telemetry import record_scan_observation
from app.services import HealthRegistry
from app.venues.polymarket import (
    MARKET_WS_URL,
    EventContext,
    OrderBook,
    PolymarketPublicClient,
    StructuralArbitrageAnalyzer,
    StructuralOpportunity,
)

log = logging.getLogger("edge_lab.m6j_polymarket")


async def _study_id() -> str | None:
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        study = db.scalar(
            select(ForwardStudy)
            .where(
                ForwardStudy.status == "active",
                ForwardStudy.venue == "polymarket",
            )
            .order_by(ForwardStudy.started_at.asc())
            .limit(1)
        )
        return study.id if study is not None else None
    finally:
        db.close()


async def _universe(client: PolymarketPublicClient, analyzer: StructuralArbitrageAnalyzer):
    settings = get_settings()
    service = PolymarketResearchService(client=client, health=HealthRegistry(), analyzer=analyzer)
    discovered = await service.discover_markets(max_markets=settings.m6j_polymarket_max_markets)
    validated, rejected = await service._validate_markets(discovered)

    token_ids = [
        token
        for market in validated
        for token in (market.yes_token_id, market.no_token_id)
        if token
    ]
    books, book_rejections = await service.fetch_books(token_ids)
    service._remove_book_metadata_mismatches(validated, books, rejected)
    for key, value in book_rejections.items():
        rejected[key] = rejected.get(key, 0) + value

    events, event_rejections = await service._load_negrisk_events(
        validated,
        max_events=settings.polymarket_max_negrisk_events,
    )
    for key, value in event_rejections.items():
        rejected[key] = rejected.get(key, 0) + value
    event_markets = [market for event in events for market in event.markets]
    extra_tokens = [
        token
        for market in event_markets
        for token in (market.yes_token_id, market.no_token_id)
        if token and token not in books
    ]
    if extra_tokens:
        extra_books, extra_rejections = await service.fetch_books(extra_tokens)
        books.update(extra_books)
        for key, value in extra_rejections.items():
            rejected[key] = rejected.get(key, 0) + value
    service._remove_book_metadata_mismatches(event_markets, books, rejected)

    all_markets = {market.market_id: market for market in [*validated, *event_markets]}
    market_by_token = {}
    for market in all_markets.values():
        if market.yes_token_id:
            market_by_token[market.yes_token_id] = market
        if market.no_token_id:
            market_by_token[market.no_token_id] = market

    event_by_token: dict[str, EventContext] = {}
    for event in events:
        for market in event.markets:
            for token in (market.yes_token_id, market.no_token_id):
                if token:
                    event_by_token[token] = event

    subscribed = list(
        dict.fromkeys(
            token
            for token in [*token_ids, *extra_tokens]
            if token in books and token in market_by_token
        )
    )
    return list(all_markets.values()), events, books, market_by_token, event_by_token, subscribed, rejected


def _opportunity_key(opportunity: StructuralOpportunity, books: dict[str, OrderBook]) -> str:
    state = []
    for leg in sorted(opportunity.legs, key=lambda item: item.token_id):
        book = books.get(leg.token_id)
        state.append(
            "|".join(
                [
                    leg.token_id,
                    str(book.book_hash if book else ""),
                    str(book.timestamp.isoformat() if book else ""),
                ]
            )
        )
    raw = "|".join(
        [
            opportunity.kind,
            str(opportunity.event_id or ""),
            str(opportunity.condition_id or ""),
            *state,
        ]
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _record_opportunity(
    study_id: str,
    opportunity: StructuralOpportunity,
    books: dict[str, OrderBook],
) -> None:
    settings = get_settings()
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        record_scan_observation(
            db,
            study_id=study_id,
            external_key=f"m6j:polymarket:edge:{_opportunity_key(opportunity, books)}",
            observation_kind="candidate",
            observed_at=opportunity.captured_at,
            metadata={
                "research_lane": "m6j",
                "research_mode": "public_websocket_observation_only",
                "kind": opportunity.kind,
                "event_id": opportunity.event_id,
                "condition_id": opportunity.condition_id,
                "roi_bps": str(opportunity.roi_bps),
                "net_profit_usd": str(opportunity.net_profit),
                "quantity": str(opportunity.quantity),
                "total_cost_usd": str(opportunity.total_cost),
                "baseline_edge_qualified": opportunity.roi_bps
                >= Decimal(str(settings.polymarket_min_edge_bps)),
                "leg_count": len(opportunity.legs),
            },
        )
    finally:
        db.close()


def _record_summary(
    study_id: str,
    *,
    started_at: datetime,
    checks: int,
    positive_checks: int,
    positive_edges: int,
    baseline_edges: int,
    binary_checks: int,
    negrisk_checks: int,
    book_events: int,
    messages: int,
    rejection_counts: Counter[str],
    markets: int,
    events: int,
    subscribed_assets: int,
) -> None:
    settings = get_settings()
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        bucket = int(started_at.timestamp() // settings.m6j_polymarket_summary_seconds)
        record_scan_observation(
            db,
            study_id=study_id,
            external_key=f"m6j:polymarket:cycle:{bucket}",
            observation_kind="cycle",
            observed_at=started_at,
            examined_count=checks,
            accepted_count=positive_checks,
            rejected_count=max(0, checks - positive_checks),
            rejection_reasons=dict(rejection_counts),
            metadata={
                "research_lane": "m6j",
                "research_mode": "public_websocket_observation_only",
                "m6j_ws_messages": messages,
                "m6j_book_events": book_events,
                "m6j_pair_checks": checks,
                "m6j_binary_checks": binary_checks,
                "m6j_negrisk_checks": negrisk_checks,
                "m6j_positive_checks": positive_checks,
                "m6j_positive_edge_events": positive_edges,
                "m6j_baseline_10bps_edge_events": baseline_edges,
                "m6j_markets_subscribed": markets,
                "m6j_negrisk_events_subscribed": events,
                "m6j_assets_subscribed": subscribed_assets,
            },
        )
    finally:
        db.close()


def _count_opportunity(
    opportunity: StructuralOpportunity,
    *,
    settings,
) -> tuple[int, int]:
    baseline = int(opportunity.roi_bps >= Decimal(str(settings.polymarket_min_edge_bps)))
    return 1, baseline


async def _stream_once(client: PolymarketPublicClient, study_id: str) -> None:
    settings = get_settings()
    analyzer = StructuralArbitrageAnalyzer(
        min_edge_bps=Decimal(str(settings.m6j_polymarket_min_edge_bps)),
        max_shares=Decimal(str(settings.polymarket_max_shares_per_opportunity)),
        max_book_age_seconds=settings.m6j_polymarket_max_book_age_seconds,
        fee_buffer_pct=Decimal(str(settings.polymarket_forward_fee_buffer_pct)),
    )
    (
        markets,
        events,
        books,
        market_by_token,
        event_by_token,
        token_ids,
        discovery_rejections,
    ) = await _universe(client, analyzer)
    if not token_ids:
        raise RuntimeError("M6J Polymarket discovery produced no websocket assets")

    messages = book_events = checks = positive_checks = positive_edges = baseline_edges = 0
    binary_checks = negrisk_checks = 0
    rejection_counts: Counter[str] = Counter(discovery_rejections)
    summary_started = datetime.now(timezone.utc)
    connected_at = time.monotonic()

    async with websockets.connect(MARKET_WS_URL, ping_interval=None, close_timeout=5) as ws:
        await ws.send(json.dumps({"assets_ids": token_ids, "type": "market"}, separators=(",", ":")))
        while True:
            if time.monotonic() - connected_at >= settings.m6j_polymarket_refresh_seconds:
                break
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=10)
            except TimeoutError:
                await ws.send("PING")
                continue
            if raw == "PONG":
                continue
            try:
                payload = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            rows = payload if isinstance(payload, list) else [payload]
            for row in rows:
                if not isinstance(row, dict):
                    continue
                messages += 1
                if row.get("event_type") != "book":
                    continue
                asset_id = str(row.get("asset_id") or "")
                seed = books.get(asset_id)
                market = market_by_token.get(asset_id)
                if seed is None or market is None:
                    continue
                try:
                    books[asset_id] = polymarket_book_from_ws(seed, row)
                except ValueError:
                    rejection_counts["INVALID_WS_BOOK"] += 1
                    continue
                book_events += 1

                yes = books.get(market.yes_token_id or "")
                no = books.get(market.no_token_id or "")
                if yes is not None and no is not None:
                    checks += 1
                    binary_checks += 1
                    opportunity, reasons = analyzer.binary_complete_set(
                        market,
                        books,
                        now=max(yes.timestamp, no.timestamp),
                    )
                    if opportunity is None:
                        for reason in reasons or ("NO_EXECUTABLE_EDGE",):
                            rejection_counts[str(reason)] += 1
                    else:
                        positive_checks += 1
                        edge_count, baseline_count = _count_opportunity(opportunity, settings=settings)
                        positive_edges += edge_count
                        baseline_edges += baseline_count
                        _record_opportunity(study_id, opportunity, books)

                event = event_by_token.get(asset_id)
                if event is not None:
                    checks += 1
                    negrisk_checks += 1
                    found, reasons = analyzer.neg_risk_event(
                        event,
                        books,
                        now=datetime.now(timezone.utc),
                    )
                    if not found:
                        for reason, count in reasons.items():
                            rejection_counts[str(reason)] += int(count)
                    else:
                        positive_checks += 1
                        for opportunity in found:
                            edge_count, baseline_count = _count_opportunity(opportunity, settings=settings)
                            positive_edges += edge_count
                            baseline_edges += baseline_count
                            _record_opportunity(study_id, opportunity, books)

            now = datetime.now(timezone.utc)
            if (now - summary_started).total_seconds() >= settings.m6j_polymarket_summary_seconds:
                _record_summary(
                    study_id,
                    started_at=summary_started,
                    checks=checks,
                    positive_checks=positive_checks,
                    positive_edges=positive_edges,
                    baseline_edges=baseline_edges,
                    binary_checks=binary_checks,
                    negrisk_checks=negrisk_checks,
                    book_events=book_events,
                    messages=messages,
                    rejection_counts=rejection_counts,
                    markets=len(markets),
                    events=len(events),
                    subscribed_assets=len(token_ids),
                )
                messages = book_events = checks = positive_checks = positive_edges = baseline_edges = 0
                binary_checks = negrisk_checks = 0
                rejection_counts = Counter()
                summary_started = now

    if messages or book_events or checks:
        _record_summary(
            study_id,
            started_at=summary_started,
            checks=checks,
            positive_checks=positive_checks,
            positive_edges=positive_edges,
            baseline_edges=baseline_edges,
            binary_checks=binary_checks,
            negrisk_checks=negrisk_checks,
            book_events=book_events,
            messages=messages,
            rejection_counts=rejection_counts,
            markets=len(markets),
            events=len(events),
            subscribed_assets=len(token_ids),
        )


async def run() -> None:
    settings = get_settings()
    if not settings.m6j_enabled:
        log.info("M6J is disabled")
        return
    async with PolymarketPublicClient(timeout_seconds=settings.polymarket_timeout_seconds) as client:
        while True:
            study_id = await _study_id()
            if study_id is None:
                await asyncio.sleep(10)
                continue
            try:
                await _stream_once(client, study_id)
            except Exception:
                log.exception("M6J Polymarket websocket session failed")
                await asyncio.sleep(5)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
