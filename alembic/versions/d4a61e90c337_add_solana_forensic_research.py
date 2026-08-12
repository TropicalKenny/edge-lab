"""add solana forensic research

Revision ID: d4a61e90c337
Revises: 8c27f4a91b02
Create Date: 2026-08-12 23:20:00
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "d4a61e90c337"
down_revision: Union[str, Sequence[str], None] = "8c27f4a91b02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "solana_launch_events",
        sa.Column("id", sa.String(36), nullable=False), sa.Column("signature", sa.String(100), nullable=False),
        sa.Column("slot", sa.Integer(), nullable=False), sa.Column("creator", sa.String(64), nullable=False),
        sa.Column("mint", sa.String(64), nullable=False), sa.Column("program_id", sa.String(64), nullable=False),
        sa.Column("logs_json", sa.Text(), nullable=False), sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("signature", "mint", name="solana_launch_signature_mint_unique"),
    )
    for c in ("signature", "slot", "creator", "mint", "observed_at"):
        op.create_index(f"ix_solana_launch_events_{c}", "solana_launch_events", [c])

    op.create_table(
        "solana_dex_snapshots",
        sa.Column("id", sa.String(36), nullable=False), sa.Column("mint", sa.String(64), nullable=False),
        sa.Column("pair_address", sa.String(64), nullable=False), sa.Column("dex_id", sa.String(64), nullable=False),
        sa.Column("quote_symbol", sa.String(32), nullable=False), sa.Column("price_usd", sa.Numeric(28,12), nullable=False),
        sa.Column("liquidity_usd", sa.Numeric(28,8), nullable=False), sa.Column("market_cap", sa.Numeric(28,8), nullable=False),
        sa.Column("volume_5m", sa.Numeric(28,8), nullable=False), sa.Column("volume_1h", sa.Numeric(28,8), nullable=False),
        sa.Column("buys_5m", sa.Integer(), nullable=False), sa.Column("sells_5m", sa.Integer(), nullable=False),
        sa.Column("buys_1h", sa.Integer(), nullable=False), sa.Column("sells_1h", sa.Integer(), nullable=False),
        sa.Column("price_change_5m", sa.Numeric(20,8), nullable=False), sa.Column("price_change_1h", sa.Numeric(20,8), nullable=False),
        sa.Column("price_change_6h", sa.Numeric(20,8), nullable=False), sa.Column("price_change_24h", sa.Numeric(20,8), nullable=False),
        sa.Column("pair_created_at", sa.DateTime(timezone=True), nullable=True), sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    for c in ("mint", "pair_address", "captured_at"):
        op.create_index(f"ix_solana_dex_snapshots_{c}", "solana_dex_snapshots", [c])

    op.create_table(
        "solana_security_snapshots",
        sa.Column("id", sa.String(36), nullable=False), sa.Column("mint", sa.String(64), nullable=False),
        sa.Column("mintable", sa.Boolean(), nullable=True), sa.Column("freezable", sa.Boolean(), nullable=True),
        sa.Column("non_transferable", sa.Boolean(), nullable=True), sa.Column("metadata_mutable", sa.Boolean(), nullable=True),
        sa.Column("malicious_creator", sa.Boolean(), nullable=True), sa.Column("top10_holder_pct", sa.Numeric(20,8), nullable=True),
        sa.Column("transfer_fee_rate", sa.Numeric(20,8), nullable=True), sa.Column("trusted_token", sa.Boolean(), nullable=True),
        sa.Column("raw_json", sa.Text(), nullable=False), sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    for c in ("mint", "captured_at"):
        op.create_index(f"ix_solana_security_snapshots_{c}", "solana_security_snapshots", [c])

    op.create_table(
        "solana_shadow_quotes",
        sa.Column("id", sa.String(36), nullable=False), sa.Column("mint", sa.String(64), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False), sa.Column("input_mint", sa.String(64), nullable=False),
        sa.Column("output_mint", sa.String(64), nullable=False), sa.Column("in_amount", sa.Numeric(38,0), nullable=False),
        sa.Column("out_amount", sa.Numeric(38,0), nullable=False), sa.Column("in_usd_value", sa.Numeric(28,10), nullable=True),
        sa.Column("out_usd_value", sa.Numeric(28,10), nullable=True), sa.Column("price_impact_pct", sa.Numeric(20,10), nullable=True),
        sa.Column("fee_bps", sa.Integer(), nullable=True), sa.Column("fee_mint", sa.String(64), nullable=True),
        sa.Column("platform_fee_amount", sa.Numeric(38,0), nullable=True), sa.Column("signature_fee_lamports", sa.Integer(), nullable=True),
        sa.Column("prioritization_fee_lamports", sa.Integer(), nullable=True), sa.Column("router", sa.String(64), nullable=True),
        sa.Column("mode", sa.String(32), nullable=True), sa.Column("request_id", sa.String(100), nullable=True),
        sa.Column("quote_time_ms", sa.Integer(), nullable=True), sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    for c in ("mint", "direction", "captured_at"):
        op.create_index(f"ix_solana_shadow_quotes_{c}", "solana_shadow_quotes", [c])

    op.create_table(
        "solana_forensic_feature_snapshots",
        sa.Column("id", sa.String(36), nullable=False), sa.Column("mint", sa.String(64), nullable=False),
        sa.Column("creator", sa.String(64), nullable=True), sa.Column("source", sa.String(32), nullable=False),
        sa.Column("age_minutes", sa.Numeric(20,4), nullable=True), sa.Column("liquidity_usd", sa.Numeric(28,8), nullable=True),
        sa.Column("market_cap", sa.Numeric(28,8), nullable=True), sa.Column("momentum_score", sa.Numeric(20,10), nullable=True),
        sa.Column("sell_ratio_5m", sa.Numeric(20,10), nullable=True), sa.Column("volume_acceleration", sa.Numeric(20,10), nullable=True),
        sa.Column("liquidity_to_mcap", sa.Numeric(20,10), nullable=True), sa.Column("price_change_5m", sa.Numeric(20,8), nullable=True),
        sa.Column("price_change_1h", sa.Numeric(20,8), nullable=True), sa.Column("mintable", sa.Boolean(), nullable=True),
        sa.Column("freezable", sa.Boolean(), nullable=True), sa.Column("malicious_creator", sa.Boolean(), nullable=True),
        sa.Column("top10_holder_pct", sa.Numeric(20,8), nullable=True), sa.Column("transfer_fee_rate", sa.Numeric(20,8), nullable=True),
        sa.Column("exit_quote_usd", sa.Numeric(28,10), nullable=True), sa.Column("exit_price_impact_pct", sa.Numeric(20,10), nullable=True),
        sa.Column("missing_fields_json", sa.Text(), nullable=False), sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    for c in ("mint", "creator", "captured_at"):
        op.create_index(f"ix_solana_forensic_feature_snapshots_{c}", "solana_forensic_feature_snapshots", [c])

    op.create_table(
        "solana_forward_labels",
        sa.Column("id", sa.String(36), nullable=False), sa.Column("mint", sa.String(64), nullable=False),
        sa.Column("launch_signature", sa.String(100), nullable=False), sa.Column("horizon_minutes", sa.Integer(), nullable=False),
        sa.Column("entry_price_usd", sa.Numeric(28,12), nullable=True), sa.Column("future_price_usd", sa.Numeric(28,12), nullable=True),
        sa.Column("return_pct", sa.Numeric(20,8), nullable=True), sa.Column("max_observed_liquidity_usd", sa.Numeric(28,8), nullable=True),
        sa.Column("exit_quote_available", sa.Boolean(), nullable=True), sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mint", "horizon_minutes", "launch_signature", name="solana_label_mint_horizon_launch_unique"),
    )
    for c in ("mint", "launch_signature", "horizon_minutes"):
        op.create_index(f"ix_solana_forward_labels_{c}", "solana_forward_labels", [c])


def downgrade() -> None:
    for table, cols in (
        ("solana_forward_labels", ("horizon_minutes", "launch_signature", "mint")),
        ("solana_forensic_feature_snapshots", ("captured_at", "creator", "mint")),
        ("solana_shadow_quotes", ("captured_at", "direction", "mint")),
        ("solana_security_snapshots", ("captured_at", "mint")),
        ("solana_dex_snapshots", ("captured_at", "pair_address", "mint")),
        ("solana_launch_events", ("observed_at", "mint", "creator", "slot", "signature")),
    ):
        for c in cols:
            op.drop_index(f"ix_{table}_{c}", table_name=table)
        op.drop_table(table)
