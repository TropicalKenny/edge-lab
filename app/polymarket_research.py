from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.services import HealthRegistry
from app.venues.polymarket import (
    EventContext,
    MarketContext,
    OrderBook,
    PolymarketPublicClient,
    PolymarketPublicError,
    StructuralArbitrageAnalyzer,
    StructuralOpportunity,
    StructuralScanResult,
    parse_book,
    parse_event,
    parse_market,
)
from app.venues.polymarket_models import (
    PolymarketBookSnapshot,
    PolymarketEventSnapshot,
    PolymarketMarketSnapshot,
    PolymarketStructuralOpportunitySnapshot,
)


def _json_default(value: Any):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"not JSON serializable: {type(value)!r}")


class PolymarketSnapshotRepository:
    @staticmethod
    def save_event(db: Session, event: EventContext) -> None:
        db.add(
            PolymarketEventSnapshot(
                event_id=event.event_id,
                title=event.title,
                slug=event.slug,
                neg_risk=event.neg_risk,
                neg_risk_augmented=event.neg_risk_augmented,
                resolution_source=event.resolution_source,
                description=event.description,
                captured_at=event.captured_at,
            )
        )

    @staticmethod
    def save_markets(db: Session, markets: list[MarketContext]) -> None:
        db.add_all(
            [
                PolymarketMarketSnapshot(
                    market_id=m.market_id,
                    condition_id=m.condition_id,
                    event_id=m.event_id,
                    question=m.question,
                    slug=m.slug,
                    yes_token_id=m.yes_token_id,
                    no_token_id=m.no_token_id,
                    accepting_orders=m.accepting_orders,
                    neg_risk=m.neg_risk,
                    neg_risk_other=m.neg_risk_other,
                    fees_enabled=m.fees_enabled,
                    fee_rate=m.fee_schedule.rate if m.fee_schedule else None,
                    fee_exponent=m.fee_schedule.exponent if m.fee_schedule else None,
                    resolution_source=m.resolution_source,
                    description=m.description,
                    end_date=m.end_date,
                    captured_at=m.captured_at,
                )
                for m in markets
            ]
        )

    @staticmethod
    def save_books(db: Session, books: list[OrderBook]) -> None:
        db.add_all(
            [
                PolymarketBookSnapshot(
                    condition_id=b.condition_id,
                    token_id=b.token_id,
                    best_bid=b.bids[0].price if b.bids else None,
                    best_ask=b.asks[0].price if b.asks else None,
                    bid_depth_shares=sum((x.size for x in b.bids), Decimal("0")),
                    ask_depth_shares=sum((x.size for x in b.asks), Decimal("0")),
                    min_order_size=b.min_order_size,
                    tick_size=b.tick_size,
                    neg_risk=b.neg_risk,
                    book_hash=b.book_hash,
                    bids_json=json.dumps([asdict(x) for x in b.bids], default=_json_default, separators=(",", ":")),
                    asks_json=json.dumps([asdict(x) for x in b.asks], default=_json_default, separators=(",", ":")),
                    book_timestamp=b.timestamp,
                    captured_at=b.captured_at,
                )
                for b in books
            ]
        )

    @staticmethod
    def save_opportunities(db: Session, opportunities: list[StructuralOpportunity]) -> None:
        db.add_all(
            [
                PolymarketStructuralOpportunitySnapshot(
                    kind=o.kind,
                    event_id=o.event_id,
                    condition_id=o.condition_id,
                    quantity=o.quantity,
                    gross_cost=o.gross_cost,
                    total_fees=o.total_fees,
                    total_cost=o.total_cost,
                    payout=o.payout,
                    net_profit=o.net_profit,
                    roi_bps=o.roi_bps,
                    eligible=o.eligible,
                    reasons_json=json.dumps(list(o.reasons), separators=(",", ":")),
                    legs_json=json.dumps([asdict(x) for x in o.legs], default=_json_default, separators=(",", ":")),
                    captured_at=o.captured_at,
                )
                for o in opportunities
            ]
        )


class PolymarketResearchService:
    """Public-data structural-research service. There is no authenticated order path."""

    def __init__(
        self,
        *,
        client: PolymarketPublicClient,
        health: HealthRegistry,
        analyzer: StructuralArbitrageAnalyzer,
    ) -> None:
        self.client = client
        self.health = health
        self.analyzer = analyzer

    @staticmethod
    def _bump(counts: dict[str, int], reason: str, amount: int = 1) -> None:
        counts[reason] = counts.get(reason, 0) + amount

    async def discover_markets(self, *, max_markets: int = 50) -> list[MarketContext]:
        if max_markets < 1 or max_markets > 500:
            raise ValueError("max_markets must be between 1 and 500")
        found: list[MarketContext] = []
        cursor: str | None = None
        pages = 0
        while len(found) < max_markets:
            page = await self.client.list_markets_page(
                limit=min(100, max_markets - len(found)),
                after_cursor=cursor,
                closed=False,
            )
            rows = page.get("markets", []) if isinstance(page, dict) else []
            if not isinstance(rows, list):
                raise PolymarketPublicError("unexpected Gamma keyset response shape")
            captured = datetime.now(timezone.utc)
            for row in rows:
                if not isinstance(row, dict):
                    continue
                try:
                    market = parse_market(row, captured_at=captured)
                except PolymarketPublicError:
                    continue
                if market.is_tradeable_binary:
                    found.append(market)
                    if len(found) >= max_markets:
                        break
            next_cursor = page.get("next_cursor") if isinstance(page, dict) else None
            if not next_cursor or not rows:
                break
            cursor = str(next_cursor)
            pages += 1
            if pages >= 10:
                break
        return found

    async def fetch_books(self, token_ids: list[str]) -> tuple[dict[str, OrderBook], dict[str, int]]:
        unique = list(dict.fromkeys(token_ids))
        books: dict[str, OrderBook] = {}
        rejected: dict[str, int] = {}
        for start in range(0, len(unique), 100):
            chunk = unique[start : start + 100]
            payloads = await self.client.get_books(chunk)
            captured = datetime.now(timezone.utc)
            for row in payloads:
                if not isinstance(row, dict):
                    self._bump(rejected, "INVALID_BOOK_RESPONSE")
                    continue
                try:
                    book = parse_book(row, captured_at=captured)
                except PolymarketPublicError:
                    self._bump(rejected, "INVALID_BOOK_RESPONSE")
                    continue
                books[book.token_id] = book
        missing = len(unique) - len(books)
        if missing > 0:
            rejected["MISSING_BOOK"] = rejected.get("MISSING_BOOK", 0) + missing
        return books, rejected

    async def _load_negrisk_events(
        self,
        markets: list[MarketContext],
        *,
        max_events: int,
    ) -> list[EventContext]:
        ids = list(dict.fromkeys(m.event_id for m in markets if m.neg_risk and m.event_id))[:max_events]
        if not ids:
            return []
        payloads = await asyncio.gather(*(self.client.get_event(str(event_id)) for event_id in ids), return_exceptions=True)
        events: list[EventContext] = []
        for payload in payloads:
            if isinstance(payload, Exception) or not isinstance(payload, dict):
                continue
            try:
                event = parse_event(payload)
            except PolymarketPublicError:
                continue
            if event.neg_risk:
                events.append(event)
        return events

    async def scan(
        self,
        db: Session | None,
        *,
        max_markets: int = 50,
        max_negrisk_events: int = 8,
        persist: bool = True,
    ) -> StructuralScanResult:
        rejected: dict[str, int] = {}
        try:
            markets = await self.discover_markets(max_markets=max_markets)
            if not markets:
                raise RuntimeError("Polymarket discovery returned no tradeable binary markets")
            token_ids = [
                token
                for market in markets
                for token in (market.yes_token_id, market.no_token_id)
                if token
            ]
            books, book_rejections = await self.fetch_books(token_ids)
            for key, value in book_rejections.items():
                rejected[key] = rejected.get(key, 0) + value

            opportunities: list[StructuralOpportunity] = []
            for market in markets:
                opportunity, reasons = self.analyzer.binary_complete_set(market, books)
                if opportunity is not None:
                    opportunities.append(opportunity)
                for reason in reasons:
                    self._bump(rejected, reason)

            events = await self._load_negrisk_events(markets, max_events=max_negrisk_events)
            event_markets = [m for event in events for m in event.markets if m.is_tradeable_binary]
            extra_tokens = [
                token
                for market in event_markets
                for token in (market.yes_token_id, market.no_token_id)
                if token and token not in books
            ]
            if extra_tokens:
                extra_books, extra_rejections = await self.fetch_books(extra_tokens)
                books.update(extra_books)
                for key, value in extra_rejections.items():
                    rejected[key] = rejected.get(key, 0) + value
            for event in events:
                found, event_rejections = self.analyzer.neg_risk_event(event, books)
                opportunities.extend(found)
                for key, value in event_rejections.items():
                    rejected[key] = rejected.get(key, 0) + value

            if persist:
                if db is None:
                    raise RuntimeError("database session required when persist=True")
                PolymarketSnapshotRepository.save_markets(db, markets)
                PolymarketSnapshotRepository.save_books(db, list(books.values()))
                for event in events:
                    PolymarketSnapshotRepository.save_event(db, event)
                PolymarketSnapshotRepository.save_opportunities(db, opportunities)
                db.commit()

            self.health.set(
                "polymarket",
                True,
                f"public structural scan: {len(markets)} markets/{len(events)} neg-risk events/{len(opportunities)} edges",
            )
            return StructuralScanResult(
                opportunities=tuple(sorted(opportunities, key=lambda o: o.net_profit, reverse=True)),
                rejection_counts=rejected,
            )
        except Exception as exc:
            if db is not None:
                db.rollback()
            self.health.set("polymarket", False, str(exc))
            raise


def public_scan_dict(result: StructuralScanResult) -> dict[str, Any]:
    return {
        "opportunities": [
            {
                **asdict(opportunity),
                "reasons": list(opportunity.reasons),
                "legs": [asdict(leg) for leg in opportunity.legs],
            }
            for opportunity in result.opportunities
        ],
        "rejection_counts": result.rejection_counts,
    }
