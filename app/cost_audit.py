"""Read-only full-journal diagnostics; never rewrites research evidence."""
import json
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session
from app.forward_models import ForwardExecutionRecord, ForwardTradeRecord

ZERO = Decimal('0')
TOLERANCE = Decimal('0.00000001')
ACCOUNTING = 'quote_value_change_minus_entry_and_exit_quote_deterioration'


def metadata(raw):
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


def quote_cashflow(info):
    """Quote USD-value proxy, not settlement or verified network costs."""
    try:
        values = {key: Decimal(str(info[key])) for key in
                  ('entry_in_usd', 'entry_out_usd', 'exit_in_usd', 'exit_out_usd')}
        if any(not v.is_finite() or v < ZERO for v in values.values()):
            return None
        if values['entry_in_usd'] <= ZERO or values['entry_out_usd'] <= ZERO:
            return None
        if info.get('status') == 'forced_loss':
            if values['exit_in_usd'] != ZERO or values['exit_out_usd'] != ZERO:
                return None
        elif info.get('status') != 'closed' or values['exit_in_usd'] <= ZERO or values['exit_out_usd'] <= ZERO:
            return None
        return values['exit_out_usd'] - values['entry_in_usd']
    except (KeyError, ValueError, TypeError, ArithmeticError):
        return None


def study_cost_audit(db: Session, study_id: str, *, as_of) -> dict:
    result = dict(scope='all_closed_trades_through_capture', trade_count=0,
                  accounting_identity_mismatch_count=0, quote_eligible_count=0,
                  quote_reconciled_count=0, quote_missing_or_invalid_count=0,
                  quote_cashflow_mismatch_count=0,
                  network_costs_verified=False, settlement_verified=False)
    fields = ('gross_pnl_usd', 'net_pnl_usd', 'fees_usd', 'slippage_usd', 'allocated_capital_usd')
    for key in fields + ('quote_cashflow_pnl_usd', 'quote_cashflow_minus_recorded_net_usd'):
        result[key] = ZERO
    query = select(ForwardTradeRecord).where(
        ForwardTradeRecord.study_id == study_id,
        ForwardTradeRecord.closed_at <= as_of,
    ).execution_options(yield_per=200)
    for batch in db.scalars(query).partitions(200):
        items = [(row, metadata(row.metadata_json)) for row in batch]
        keys = [m.get('exit_execution_key') for _, m in items
                if m.get('accounting') == ACCOUNTING and isinstance(m.get('exit_execution_key'), str)]
        exits = {row.external_key: metadata(row.metadata_json) for row in db.scalars(
            select(ForwardExecutionRecord).where(
                ForwardExecutionRecord.study_id == study_id,
                ForwardExecutionRecord.external_key.in_(keys),
                ForwardExecutionRecord.observed_at <= as_of,
            ))} if keys else {}
        for row, info in items:
            result['trade_count'] += 1
            for key in fields:
                result[key] += Decimal(getattr(row, key))
            identity = row.gross_pnl_usd - row.fees_usd - row.slippage_usd - row.net_pnl_usd
            result['accounting_identity_mismatch_count'] += int(abs(identity) > TOLERANCE)
            if info.get('accounting') != ACCOUNTING:
                continue
            result['quote_eligible_count'] += 1
            key = info.get('exit_execution_key')
            exit_info = exits.get(key, {}) if isinstance(key, str) else {}
            cashflow = quote_cashflow(exit_info)
            if not info.get('launch_signature') or exit_info.get('launch_signature') != info['launch_signature']:
                cashflow = None
            if cashflow is None:
                result['quote_missing_or_invalid_count'] += 1
                continue
            result['quote_reconciled_count'] += 1
            delta = cashflow - row.net_pnl_usd
            result['quote_cashflow_pnl_usd'] += cashflow
            result['quote_cashflow_minus_recorded_net_usd'] += delta
            result['quote_cashflow_mismatch_count'] += int(abs(delta) > TOLERANCE)
    allocated = result['allocated_capital_usd']
    result['recorded_cost_bps_of_allocations'] = (
        (result['fees_usd'] + result['slippage_usd']) / allocated * Decimal('10000')
        if allocated > ZERO else None
    )
    result['quote_cashflow_scope'] = 'reconciled_subset_only; quote USD values, not settlement'
    return result
