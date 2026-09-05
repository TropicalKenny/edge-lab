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
from app.m6k_research import polymarket_negrisk_yes_consistency
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


def _event_state_key(event: EventContext, books: dict[str, OrderBook]) -> str:
    state = [event.event_id]
    for market in sorted(event.markets, key=lambda item: item.market_id):
        token = market.yes_token_id or ""
        book = books.get(token)
        state.append(
            "|".join(
                [
                    market.market_id,
                    token,
                    str(book.book_hash if book else ""),
                    str(book.timestamp.isoformat() if book else ""),
                ]
            )
        )
    return hashlib.sha256("|".join(state).encode()).hexdigest()[:24]


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


def _record_event_consistency(
    study_id: str,
    event: EventContext,
    books: dict[str, OrderBook],
    *,
    now: datetime,
) -> tuple[bool, bool, tuple[str, ...]]:
    settings = get_settings()
    observation, reasons = polymarket_negrisk_yes_consistency(
        event,
        books,
        now=now,
        max_shares=Decimal(str(settings.polymarket_max_shares_per_opportunity)),
        max_book_age_seconds=settings.m6j_polymarket_max_book_age_seconds,
        fee_buffer_pct=Decimal(str(settings.polymarket_forward_fee_buffer_pct)),
        baseline_edge_bps=Decimal(str(settings.m6k_polymarket_baseline_edge_bps)),
    )
    if observation is None:
        return False, False, reasons

    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        state_key = _event_state_key(event, books)
        record_scan_observation(
            db,
            study_id=study_id,
            external_key=f"m6k:pm:event-consistency:{event.event_id}:{state_key}",
            observation_kind="candidate",
            observed_at=now,
            rejection_reasons=(
                {}
                if observation.positive_violation
                else {"NO_POSITIVE_EVENT_CONSISTENCY_GAP": 1}
            ),
            metadata={
                "research_lane": "m6k-pm",
                "research_mode": "metadata_invariant_public_book_observation_only",
                "screen_version": "m6k-pm-v1",
                "relationship_type": "standard_negrisk_yes_complete_set",
                "relationship_source": "explicit_negrisk_event_metadata",
                "event_id": observation.event_id,
                "market_count": observation.market_count,
                "quantity": str(observation.quantity),
                "gross_cost_usd": str(observation.gross_cost),
                "total_fees_usd": str(observation.total_fees),
                "total_cost_usd": str(observation.total_cost),
                "deterministic_resolution_payout_usd": str(observation.payout),
                "gap_usd": str(observation.gap_usd),
                "gap_bps": str(observation.gap_bps),
                "positive_violation": observation.positive_violation,
                "baseline_edge_qualified": observation.baseline_edge_qualified,
                "baseline_edge_bps": str(settings.m6k_polymarket_baseline_edge_bps),
                "state_key": state_key,
                "duration_semantics": (
                    "infer-from-consecutive-unique-book-state-observations"
                ),
                "uses_resolved_outcome": False,
                "semantic_llm_relationship_inference": False,
            },
        )
    finally:
        db.close()
    return True, observation.positive_violation, ()


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
    m6k_checks: int,
    m6k_valid: int,
    m6k_positive: int,
    m6k_baseline: int,
    m6k_rejections: Counter[str],
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
        if settings.m6k_enabled:
            record_scan_observation(
                db,
                study_id=study_id,
                external_key=f"m6k:pm:cycle:{bucket}",
                observation_kind="cycle",
                observed_at=started_at,
                examined_count=m6k_checks,
                accepted_count=m6k_positive,
                rejected_count=max(0, m6k_checks - m6k_positive),
                rejection_reasons=dict(m6k_rejections),
                metadata={
                    "research_lane": "m6k-pm",
                    "research_mode": "metadata_invariant_public_book_observation_only",
                    "screen_version": "m6k-pm-v1",
                    "m6k_pm_event_checks": m6k_checks,
                    "m6k_pm_valid_observations": m6k_valid,
                    "m6k_pm_positive_violations": m6k_positive,
                    "m6k_pm_baseline_qualified": m6k_baseline,
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
    m6k_checks = m6k_valid = m6k_positive = m6k_baseline = 0
    rejection_counts: Counter[str] = Counter(discovery_rejections)
    m6k_rejections: Counter[str] = Counter()
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
                    event_now = datetime.now(timezone.utc)
                    checks += 1
                    negrisk_checks += 1
                    found, reasons = analyzer.neg_risk_event(
                        event,
                        books,
                        now=event_now,
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

                    if settings.m6k_enabled:
                        m6k_checks += 1
                        valid, positive_gap, consistency_reasons = _record_event_consistency(
                            study_id,
                            event,
                            books,
                            now=event_now,
                        )
                        m6k_valid += int(valid)
                        m6k_positive += int(positive_gap)
                        if valid:
                            observation, _ = polymarket_negrisk_yes_consistency(
                                event,
                                books,
                                now=event_now,
                                max_shares=Decimal(
                                    str(settings.polymarket_max_shares_per_opportunity)
                                ),
                                max_book_age_seconds=(
                                    settings.m6j_polymarket_max_book_age_seconds
                                ),
                                fee_buffer_pct=Decimal(
                                    str(settings.polymarket_forward_fee_buffer_pct)
                                ),
                                baseline_edge_bps=Decimal(
                                    str(settings.m6k_polymarket_baseline_edge_bps)
                                ),
                            )
                            m6k_baseline += int(
                                bool(observation and observation.baseline_edge_qualified)
                            )
                            if not positive_gap:
                                m6k_rejections["NO_POSITIVE_EVENT_CONSISTENCY_GAP"] += 1
                        else:
                            for reason in consistency_reasons:
                                m6k_rejections[str(reason)] += 1

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
                    m6k_checks=m6k_checks,
                    m6k_valid=m6k_valid,
                    m6k_positive=m6k_positive,
                    m6k_baseline=m6k_baseline,
                    m6k_rejections=m6k_rejections,
                )
                messages = book_events = checks = positive_checks = positive_edges = baseline_edges = 0
                binary_checks = negrisk_checks = 0
                m6k_checks = m6k_valid = m6k_positive = m6k_baseline = 0
                rejection_counts = Counter()
                m6k_rejections = Counter()
                summary_started = now

    if messages or book_events or checks or m6k_checks:
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
            m6k_checks=m6k_checks,
            m6k_valid=m6k_valid,
            m6k_positive=m6k_positive,
            m6k_baseline=m6k_baseline,
            m6k_rejections=m6k_rejections,
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
                log.exception("M6J/M6K Polymarket websocket session failed")
                await asyncio.sleep(5)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
