import json
from datetime import datetime, timezone, timedelta
from decimal import Decimal as D
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.models import Base
from app.forward_models import ForwardTradeRecord, ForwardExecutionRecord
from app.cost_audit import ACCOUNTING, quote_cashflow, study_cost_audit

NOW = datetime(2025, 1, 15, 12, tzinfo=timezone.utc)


def test_quote_cashflow_includes_favorable_values_and_forced_loss():
    info = dict(status='closed', entry_in_usd='25', entry_out_usd='26', exit_in_usd='28', exit_out_usd='29')
    assert quote_cashflow(info) == D('4')
    # Existing clamped decomposition gives 2; diagnostic exposes the difference.
    info.update(status='forced_loss', exit_in_usd='0', exit_out_usd='0')
    assert quote_cashflow(info) == D('-25')
    for bad in ('NaN', 'Infinity', '-1', None):
        assert quote_cashflow({**info, 'entry_in_usd': bad}) is None
    assert quote_cashflow({}) is None
    assert quote_cashflow({**info, 'exit_out_usd': '1'}) is None


def test_audit_full_history_cutoff_isolation_and_missing_evidence():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        for i in range(205):
            info = dict(accounting=ACCOUNTING, exit_execution_key=f'exit-{i}', launch_signature=f'sig-{i}')
            db.add(ForwardTradeRecord(study_id='a', external_key=f'trade-{i}', opened_at=NOW-timedelta(hours=1), closed_at=NOW,
                gross_pnl_usd=D('2'), net_pnl_usd=D('2'), fees_usd=0, slippage_usd=0,
                allocated_capital_usd=25, planned_loss_usd=25, metadata_json=json.dumps(info)))
            if i == 204:
                continue
            db.add(ForwardExecutionRecord(study_id='a', external_key=f'exit-{i}', observed_at=NOW, side='sell',
                intended_quantity=1, paper_filled_quantity=1, shadow_filled_quantity=1,
                metadata_json=json.dumps(dict(status='closed', launch_signature=f'sig-{i}', entry_in_usd='25',
                    entry_out_usd='26', exit_in_usd='28', exit_out_usd='29'))))
        for study, when in [('b', NOW), ('a', NOW+timedelta(days=1))]:
            db.add(ForwardTradeRecord(study_id=study, external_key='excluded', opened_at=NOW, closed_at=when,
                gross_pnl_usd=999, net_pnl_usd=999, fees_usd=0, slippage_usd=0,
                allocated_capital_usd=1000, planned_loss_usd=1000))
        db.commit()
        result = study_cost_audit(db, 'a', as_of=NOW)
        assert result['trade_count'] == 205
        assert result['net_pnl_usd'] == 410
        assert result['quote_reconciled_count'] == 204
        assert result['quote_missing_or_invalid_count'] == 1
        assert result['quote_cashflow_mismatch_count'] == 204
        assert result['quote_cashflow_minus_recorded_net_usd'] == 408
        assert result['accounting_identity_mismatch_count'] == 0
        assert result['network_costs_verified'] is False
        assert study_cost_audit(db, 'empty', as_of=NOW)['recorded_cost_bps_of_allocations'] is None
