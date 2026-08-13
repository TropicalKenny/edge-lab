from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import Base
from app.solana_research import ForwardLabelService
from app.venues.solana import PUMP_PROGRAM_ID
from app.venues.solana_models import SolanaDexSnapshot, SolanaForwardLabel, SolanaLaunchEvent

NOW = datetime(2026, 8, 12, 22, 0, tzinfo=timezone.utc)
MINT = "Timing11111111111111111111111111111111111111"


def add_snapshot(db: Session, *, minutes: int, price: str):
    db.add(
        SolanaDexSnapshot(
            mint=MINT,
            pair_address="pair",
            dex_id="raydium",
            quote_symbol="USDC",
            price_usd=Decimal(price),
            liquidity_usd=Decimal("10000"),
            market_cap=Decimal("100000"),
            volume_5m=Decimal("1000"),
            volume_1h=Decimal("12000"),
            buys_5m=10,
            sells_5m=5,
            buys_1h=50,
            sells_1h=30,
            price_change_5m=Decimal("0"),
            price_change_1h=Decimal("0"),
            price_change_6h=Decimal("0"),
            price_change_24h=Decimal("0"),
            pair_created_at=NOW,
            captured_at=NOW + timedelta(minutes=minutes),
        )
    )


def test_sparse_snapshot_is_not_mislabeled_as_five_minute_return():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.add(
        SolanaLaunchEvent(
            signature="timing-launch",
            slot=1,
            creator="creator",
            mint=MINT,
            program_id=PUMP_PROGRAM_ID,
            logs_json="[]",
            observed_at=NOW,
        )
    )
    add_snapshot(db, minutes=1, price="1")
    add_snapshot(db, minutes=16, price="2")
    add_snapshot(db, minutes=31, price="3")
    db.commit()

    created = ForwardLabelService.resolve(db, mint=MINT, horizons=(5, 30))
    labels = list(db.scalars(select(SolanaForwardLabel)).all())
    assert created == 1
    assert len(labels) == 1
    label = labels[0]
    assert label.horizon_minutes == 30
    assert label.observed_horizon_minutes == Decimal("30")
    assert label.entry_observed_at is not None
    db.close()
