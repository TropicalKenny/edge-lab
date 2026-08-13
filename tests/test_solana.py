import asyncio
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import parse_qs

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import Base
from app.solana_research import ForensicFeatureBuilder, ForwardLabelService
from app.venues.solana import (
    DexScreenerClient,
    DexSnapshot,
    GoPlusSolanaClient,
    HeliusPumpStream,
    JupiterShadowClient,
    PUMP_AMM_PROGRAM_ID,
    PUMP_PROGRAM_ID,
    SecuritySnapshot,
    SolanaResearchError,
    USDC_MINT,
    parse_pump_launch_notification,
)
from app.venues.solana_asset import HeliusAssetClient, SolanaAssetMetadata
from app.venues.solana_models import SolanaDexSnapshot, SolanaForwardLabel, SolanaLaunchEvent
from app.workers.solana_forensic_sampler import selected

NOW = datetime(2026, 8, 12, 22, 0, tzinfo=timezone.utc)
MINT = "Mint111111111111111111111111111111111111111"
CREATOR = "Creator11111111111111111111111111111111111"


def pump_notification(*, include_initialize: bool = True, include_program: bool = True):
    logs = ["Program log: Instruction: InitializeMint2"] if include_initialize else ["Program log: Instruction: Buy"]
    if include_program:
        logs.append(f"Program {PUMP_PROGRAM_ID} invoke [1]")
    keys = [{"pubkey": CREATOR}, {"pubkey": MINT}]
    if include_program:
        keys.append({"pubkey": PUMP_PROGRAM_ID})
    return {
        "method": "transactionNotification",
        "params": {
            "result": {
                "signature": "sig-launch",
                "slot": 123456,
                "transaction": {
                    "meta": {"logMessages": logs},
                    "transaction": {"message": {"accountKeys": keys}},
                },
            }
        },
    }


def test_helius_subscription_and_pump_launch_parser_are_chain_native():
    stream = HeliusPumpStream(api_key="test-key")
    payload = json.loads(stream.subscribe_message())
    assert payload["method"] == "transactionSubscribe"
    assert set(payload["params"][0]["accountInclude"]) == {PUMP_PROGRAM_ID, PUMP_AMM_PROGRAM_ID}
    assert payload["params"][1]["encoding"] == "jsonParsed"
    assert payload["params"][1]["transactionDetails"] == "full"

    event = parse_pump_launch_notification(pump_notification())
    assert event is not None
    assert event.creator == CREATOR
    assert event.mint == MINT
    assert event.program_id == PUMP_PROGRAM_ID
    assert parse_pump_launch_notification(pump_notification(include_initialize=False)) is None
    assert parse_pump_launch_notification(pump_notification(include_program=False)) is None


def test_jupiter_shadow_quote_omits_taker_and_rejects_transactions():
    seen = []

    async def handler(request: httpx.Request):
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "inputMint": MINT,
                "outputMint": USDC_MINT,
                "inAmount": "1000000",
                "outAmount": "25000000",
                "inUsdValue": "25.10",
                "outUsdValue": "25.00",
                "priceImpactPct": "0.004",
                "feeBps": 0,
                "router": "jupiterz",
                "mode": "ultra",
                "requestId": "request-1",
                "totalTime": 31,
                "transaction": None,
            },
        )

    async def run():
        async with JupiterShadowClient(api_key="jup-test", transport=httpx.MockTransport(handler)) as client:
            quote = await client.order_quote(input_mint=MINT, output_mint=USDC_MINT, amount=1_000_000)
            assert quote.out_amount == 25_000_000
            assert quote.transaction_present is False
            assert not hasattr(client, "execute")
            assert not hasattr(client, "place_order")

    asyncio.run(run())
    assert len(seen) == 1
    assert seen[0].url.path == "/swap/v2/order"
    query = parse_qs(seen[0].url.query.decode())
    assert "taker" not in query
    assert query["amount"] == ["1000000"]

    async def bad_handler(_: httpx.Request):
        return httpx.Response(200, json={"outAmount": "1", "transaction": "base64-transaction"})

    async def reject():
        async with JupiterShadowClient(api_key="jup-test", transport=httpx.MockTransport(bad_handler)) as client:
            with pytest.raises(SolanaResearchError):
                await client.order_quote(input_mint=MINT, output_mint=USDC_MINT, amount=1)

    asyncio.run(reject())


def test_dexscreener_is_enrichment_and_selects_deepest_pair():
    async def handler(request: httpx.Request):
        assert request.url.path == f"/token-pairs/v1/solana/{MINT}"
        rows = []
        for address, liquidity, price in (("thin", 1000, "0.01"), ("deep", 50000, "0.02")):
            rows.append(
                {
                    "chainId": "solana",
                    "pairAddress": address,
                    "dexId": "raydium",
                    "priceUsd": price,
                    "marketCap": 100000,
                    "liquidity": {"usd": liquidity},
                    "volume": {"m5": 5000, "h1": 24000},
                    "txns": {"m5": {"buys": 30, "sells": 10}, "h1": {"buys": 100, "sells": 50}},
                    "priceChange": {"m5": 5, "h1": 20, "h6": 30, "h24": 40},
                    "quoteToken": {"symbol": "USDC"},
                    "pairCreatedAt": int(NOW.timestamp() * 1000),
                }
            )
        return httpx.Response(200, json=rows)

    async def run():
        async with DexScreenerClient(transport=httpx.MockTransport(handler)) as client:
            snapshot = await client.token(MINT)
            assert snapshot is not None
            assert snapshot.pair_address == "deep"
            assert snapshot.liquidity_usd == Decimal("50000")
            assert not hasattr(client, "discover_new_tokens")

    asyncio.run(run())


def test_goplus_preserves_raw_security_units():
    async def handler(request: httpx.Request):
        assert request.url.path.endswith("/solana/token_security")
        return httpx.Response(
            200,
            json={
                "result": {
                    MINT: {
                        "mintable": {"status": "0"},
                        "freezable": {"status": "1"},
                        "metadata_mutable": {"status": "1"},
                        "non_transferable": "0",
                        "trusted_token": "0",
                        "creator": [{"address": CREATOR, "malicious_address": "1"}],
                        "holders": [{"percent": "0.40"}, {"percent": "0.20"}],
                        "transfer_fee": {"current_fee_rate": {"fee_rate": "2.5"}},
                    }
                }
            },
        )

    async def run():
        async with GoPlusSolanaClient(transport=httpx.MockTransport(handler)) as client:
            result = await client.token_security(MINT)
            assert result is not None
            assert result.mintable is False
            assert result.freezable is True
            assert result.malicious_creator is True
            assert result.top10_holder_pct == Decimal("0.60")
            assert result.transfer_fee_rate == Decimal("2.5")
            assert "transfer_fee" in result.raw

    asyncio.run(run())


def test_helius_asset_metadata_is_read_only_and_parses_authorities():
    async def handler(request: httpx.Request):
        body = json.loads(request.content)
        assert body["method"] == "getAsset"
        assert body["params"]["displayOptions"]["showFungible"] is True
        return httpx.Response(
            200,
            json={
                "result": {
                    "mutable": True,
                    "content": {"metadata": {"name": "Test Token", "symbol": "TEST"}},
                    "token_info": {
                        "decimals": 6,
                        "supply": "1000000000",
                        "token_program": "spl-token",
                        "mint_authority": CREATOR,
                        "freeze_authority": None,
                        "price_info": {"price_per_token": 0.02},
                    },
                }
            },
        )

    async def run():
        async with HeliusAssetClient(api_key="helius-test", transport=httpx.MockTransport(handler)) as client:
            asset = await client.get_asset(MINT)
            assert asset.decimals == 6
            assert asset.mint_authority == CREATOR
            assert asset.freeze_authority is None
            assert asset.cached_price_usd == Decimal("0.02")

    asyncio.run(run())


def test_forensic_builder_keeps_features_not_a_buy_score():
    dex = DexSnapshot(
        mint=MINT,
        pair_address="pair",
        dex_id="raydium",
        quote_symbol="USDC",
        price_usd=Decimal("0.02"),
        liquidity_usd=Decimal("20000"),
        market_cap=Decimal("100000"),
        volume_5m=Decimal("6000"),
        volume_1h=Decimal("24000"),
        buys_5m=30,
        sells_5m=10,
        buys_1h=100,
        sells_1h=50,
        price_change_5m=Decimal("5"),
        price_change_1h=Decimal("20"),
        price_change_6h=Decimal("30"),
        price_change_24h=Decimal("40"),
        pair_created_at=NOW,
        captured_at=NOW,
    )
    security = SecuritySnapshot(
        mint=MINT,
        mintable=False,
        freezable=False,
        non_transferable=False,
        metadata_mutable=False,
        malicious_creator=False,
        top10_holder_pct=Decimal("0.5"),
        transfer_fee_rate=None,
        trusted_token=False,
        raw={},
        captured_at=NOW,
    )
    asset = SolanaAssetMetadata(
        mint=MINT,
        symbol="TEST",
        name="Test",
        decimals=6,
        supply_atomic=1_000_000,
        token_program="spl-token",
        mint_authority=None,
        freeze_authority=None,
        mutable=False,
        cached_price_usd=None,
        captured_at=NOW,
    )
    values = ForensicFeatureBuilder.build(
        mint=MINT,
        creator=CREATOR,
        launch_at=NOW - timedelta(minutes=10),
        dex=dex,
        security=security,
        asset=asset,
        exit_quote=None,
        exit_test_notional_usd=None,
        now=NOW,
    )
    assert values["momentum_score"] == Decimal("0.5")
    assert values["sell_ratio_5m"] == Decimal("0.25")
    assert values["volume_acceleration"] == Decimal("3")
    assert values["liquidity_to_mcap"] == Decimal("0.2")
    assert "score" not in values and "decision" not in values


def add_dex_snapshot(db: Session, *, captured_at: datetime, price: str, liquidity: str = "10000"):
    db.add(
        SolanaDexSnapshot(
            mint=MINT,
            pair_address="pair",
            dex_id="raydium",
            quote_symbol="USDC",
            price_usd=Decimal(price),
            liquidity_usd=Decimal(liquidity),
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
            captured_at=captured_at,
        )
    )


def test_forward_labels_exclude_prelaunch_data_and_anchor_to_entry_snapshot():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.add(
        SolanaLaunchEvent(
            signature="launch-sig",
            slot=1,
            creator=CREATOR,
            mint=MINT,
            program_id=PUMP_PROGRAM_ID,
            logs_json="[]",
            observed_at=NOW,
        )
    )
    add_dex_snapshot(db, captured_at=NOW - timedelta(minutes=1), price="1")
    add_dex_snapshot(db, captured_at=NOW + timedelta(minutes=1), price="2", liquidity="10000")
    add_dex_snapshot(db, captured_at=NOW + timedelta(minutes=6), price="3", liquidity="15000")
    add_dex_snapshot(db, captured_at=NOW + timedelta(minutes=31), price="1", liquidity="12000")
    db.commit()

    created = ForwardLabelService.resolve(db, mint=MINT, horizons=(5, 30))
    labels = list(db.scalars(select(SolanaForwardLabel).order_by(SolanaForwardLabel.horizon_minutes)).all())
    assert created == 2
    assert labels[0].horizon_minutes == 5
    assert labels[0].entry_price_usd == Decimal("2")
    assert labels[0].future_price_usd == Decimal("3")
    assert labels[0].return_pct == Decimal("50")
    assert labels[1].horizon_minutes == 30
    assert labels[1].future_price_usd == Decimal("1")
    assert labels[1].return_pct == Decimal("-50")
    db.close()


def test_sampler_selection_is_deterministic_and_can_be_disabled():
    assert selected(MINT, 1) is True
    assert selected(MINT, 50) == selected(MINT, 50)
