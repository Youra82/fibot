"""Broker-free regressions for observed execution defects, not PnL curve fitting."""
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import MagicMock
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from fibot.utils import trade_manager as tm
from fibot.strategy import confluence_logic as logic
from fibot.utils.execution_guard import (
    validate_bracket, consume, consumed, entry_client_oid, symbol_cycle_lock,
)
from fibot.utils.exchange import Exchange

SYMBOL='BTC/USDT:USDT'
CFG={'market':{'symbol':SYMBOL,'timeframe':'15m'},'strategy':{'type':'confluence'},'risk':{'leverage':5,'risk_per_entry_pct':1}}
PLAN=dict(direction='long',limit=100.,sl=98.,tp=110.,rr=5.,a_ts='2025-03-30 00:00:00+00:00',b_ts='2025-03-31 00:00:00+00:00')

@pytest.fixture
def cycle(tmp_path,monkeypatch):
    monkeypatch.setattr(tm,'TRACKER_DIR',str(tmp_path))
    monkeypatch.setattr(tm,'send_message',MagicMock())
    monkeypatch.setattr(tm,'send_photo',MagicMock())
    monkeypatch.setattr(tm,'_trend_filter_reject',lambda *a:None)
    monkeypatch.setattr(tm,'_order_updates_enabled',lambda:False)
    monkeypatch.setattr(logic,'plan_next_order',lambda *a:dict(PLAN))
    df=pd.DataFrame({'open':101.,'high':102.,'low':100.,'close':101.,'volume':1.},
        index=pd.date_range(end='2025-04-01 09:45',periods=220,freq='15min',tz='UTC'))
    ex=MagicMock();ex.exchange.parse_timeframe.return_value=900
    ex.fetch_recent_ohlcv.return_value=df;ex.fetch_equity_usdt.return_value=100.;ex.fetch_balance_usdt.return_value=100.
    ex.markets={SYMBOL:{'limits':{'amount':{'min':.01}}}};ex.amount_to_precision.side_effect=lambda symbol,q:str(q)
    ex.price_to_precision.side_effect=lambda symbol,p:str(p)
    ex.fetch_open_positions.return_value=[];ex.place_limit_order_with_tpsl.return_value={'id':'new'}
    ex.cancel_order.return_value={'filled':0}
    path=tm.get_tracker_path(SYMBOL,'15m')
    tracker=dict(status='pending_entry',order_id='old',candle_ts='old',direction='long',entry_price=100.,b_ts=PLAN['b_ts'],notified_b_ts=PLAN['b_ts'])
    tm.write_tracker(path,tracker)
    return ex,path,tracker

def run(ex):tm.confluence_cycle(ex,CFG,{},logging.getLogger('test'))

def test_cancel_failure_preserves_tracker_and_never_replaces(cycle):
    ex,path,original=cycle;ex.fetch_order.return_value={'status':'open','filled':0};ex.cancel_order.side_effect=TimeoutError()
    run(ex);ex.place_limit_order_with_tpsl.assert_not_called();assert tm.read_tracker(path)==original

@pytest.mark.parametrize('after',[None,{'status':'open','filled':0},{'status':'canceled'}, {'status':'canceled','filled':float('nan')}])
def test_uncertain_cancel_or_fill_cannot_create_second_order(cycle,after):
    ex,path,original=cycle;ex.fetch_order.side_effect=[{'status':'open','filled':0},after]
    run(ex);ex.place_limit_order_with_tpsl.assert_not_called();assert tm.read_tracker(path)==original

def test_confirmed_zero_fill_cancel_allows_one_valid_replacement(cycle):
    ex,path,_=cycle;ex.fetch_order.side_effect=[{'status':'open','filled':0},{'status':'canceled','filled':0}]
    run(ex);ex.place_limit_order_with_tpsl.assert_called_once();assert tm.read_tracker(path)['order_id']=='new'

def test_fill_during_cancel_prevents_replacement_and_old_impulse_stays_consumed(cycle):
    ex,path,_=cycle;ex.fetch_order.side_effect=[{'status':'open','filled':0},{'status':'canceled','filled':.2}]
    run(ex);ex.place_limit_order_with_tpsl.assert_not_called()
    ex.fetch_order.side_effect=None;ex.fetch_order.return_value={'status':'canceled','filled':.2}
    run(ex);ex.place_limit_order_with_tpsl.assert_not_called()
    tm.write_tracker(path,{'notified_b_ts':PLAN['b_ts']})
    run(ex);ex.place_limit_order_with_tpsl.assert_not_called()

def test_fill_appearing_after_position_snapshot_does_not_cancel_protection(cycle):
    ex,path,_=cycle;ex.fetch_order.return_value={'status':'closed','filled':1};ex.fetch_open_positions.return_value=[{'contracts':1}]
    run(ex);ex.cancel_all_orders_for_symbol.assert_not_called();ex.place_limit_order_with_tpsl.assert_not_called()
    assert tm.read_tracker(path)['status']=='open'

def test_impulse_guard_survives_tracker_reset_but_allows_next_impulse(cycle,monkeypatch):
    ex,path,tracker=cycle;tracker['status']='open';tm.write_tracker(path,tracker)
    run(ex);tm.write_tracker(path,{'notified_b_ts':PLAN['b_ts']});run(ex)
    ex.place_limit_order_with_tpsl.assert_not_called()
    new=dict(PLAN,b_ts='2025-03-31 01:00:00+00:00');monkeypatch.setattr(logic,'plan_next_order',lambda *a:new)
    tm.write_tracker(path,{'notified_b_ts':new['b_ts'],'execution_guard_version':1});run(ex)
    ex.place_limit_order_with_tpsl.assert_called_once()

def test_corrupt_impulse_history_does_not_silently_forget_fills(cycle):
    ex,path,_=cycle;tm.write_tracker(path,{})
    Path(tm._impulse_path(SYMBOL,'15m')).write_text('broken',encoding='utf-8')
    run(ex);ex.place_limit_order_with_tpsl.assert_not_called()

def test_legacy_position_is_reconciled_before_new_confluence_entry(cycle):
    ex,path,_=cycle
    tm.write_tracker(path,dict(status='open',strategy='legacy',notified_b_ts=PLAN['b_ts']))
    run(ex)
    ex.place_limit_order_with_tpsl.assert_not_called()
    assert tm.read_tracker(path)['status'] == 'position_reconcile'
    ex.cancel_all_orders_for_symbol.assert_not_called()

def test_guard_write_failure_prevents_new_entry(cycle,monkeypatch):
    ex,path,_=cycle;ex.fetch_order.return_value={'status':'closed','filled':1}
    def fail(*args):raise OSError('simulated storage failure')
    monkeypatch.setattr(tm,'consume',fail)
    run(ex);ex.place_limit_order_with_tpsl.assert_not_called()

@pytest.mark.parametrize('minimum,free,rounding',[(1.,100.,False),(.1,.01,False),(.01,100.,True)])
def test_exchange_minimum_and_rounding_cannot_exceed_risk_or_margin(cycle,minimum,free,rounding):
    ex,_,_=cycle;ex.markets[SYMBOL]['limits']['amount']['min']=minimum;ex.fetch_balance_usdt.return_value=free
    if rounding:ex.amount_to_precision.side_effect=lambda *a:'1'
    assert tm._confluence_size(ex,SYMBOL,PLAN,1,5,logging.getLogger('test'))==0

def test_valid_risk_size_remains_available(cycle):
    ex,_,_=cycle
    assert tm._confluence_size(ex,SYMBOL,PLAN,1,5,logging.getLogger('test'))==.5


def test_legacy_exchange_minimum_cannot_raise_risk():
    assert tm.calc_position_size(100.,1.,100.,99.,5,logging.getLogger('test'),min_contracts=2.)==0


def test_legacy_free_margin_is_hard_limit():
    assert tm.calc_position_size(100.,1.,100.,99.,5,logging.getLogger('test'),
        min_contracts=.01,free_balance=.1)==0

def test_actual_pyth_style_quote_beyond_stop_cannot_submit_order():
    ex=Exchange.__new__(Exchange);ex.markets={SYMBOL:{}};ex.exchange=MagicMock()
    ex.amount_to_precision=lambda s,q:str(q);ex.price_to_precision=lambda s,p:str(p)
    ex.fetch_ticker=lambda s:dict(last=.06752,bid=.06751,ask=.06753)
    with pytest.raises(ValueError):ex.place_limit_order_with_tpsl(SYMBOL,'sell',10,.067,.06707,.06113)
    ex.exchange.create_order.assert_not_called()

def test_tick_rounding_cannot_collapse_stop_and_entry():
    ex=Exchange.__new__(Exchange);ex.markets={SYMBOL:{}};ex.exchange=MagicMock()
    ex.amount_to_precision=lambda s,q:str(q);ex.price_to_precision=lambda s,p:f'{p:.2f}'
    ex.fetch_ticker=lambda s:dict(last=100.01,ask=100.02,bid=100.)
    with pytest.raises(ValueError):ex.place_limit_order_with_tpsl(SYMBOL,'buy',1,100.004,100.003,110.)
    ex.exchange.create_order.assert_not_called()

@pytest.mark.parametrize('side,stop,target',[('buy',98.,110.),('sell',102.,90.)])
def test_valid_bracket_is_not_filtered_by_market_regime(side,stop,target):
    validate_bracket(side,100.,stop,target,dict(last=100.1,bid=100.,ask=100.2))

def test_lock_blocks_overlapping_process_and_releases(tmp_path):
    code='''import sys
from fibot.utils.execution_guard import symbol_cycle_lock,CycleBusy
try:
 with symbol_cycle_lock(sys.argv[1],sys.argv[2]):pass
except CycleBusy:sys.exit(3)
'''
    env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
    def child():return subprocess.run([sys.executable,'-c',code,str(tmp_path),SYMBOL],env=env,timeout=15,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)).returncode
    with symbol_cycle_lock(tmp_path,SYMBOL):assert child()==3
    assert child()==0


def test_tracker_write_is_atomic_and_failure_is_visible(tmp_path,monkeypatch):
    path=tmp_path/'tracker.json';tm.write_tracker(str(path),{'old':1})
    monkeypatch.setattr(tm.os,'replace',lambda *args:(_ for _ in ()).throw(OSError('disk')))
    with pytest.raises(OSError):tm.write_tracker(str(path),{'new':2})
    assert json.loads(path.read_text(encoding='utf-8'))=={'old':1}


def test_corrupt_tracker_is_fail_closed(tmp_path):
    path=tmp_path/'tracker.json';path.write_text('broken',encoding='utf-8')
    with pytest.raises(RuntimeError):tm.read_tracker(str(path))


def test_intent_must_persist_before_broker_request(cycle,monkeypatch):
    ex,path,_=cycle;tm.write_tracker(path,{})
    monkeypatch.setattr(tm,'write_tracker',lambda *args:(_ for _ in ()).throw(OSError('disk')))
    with pytest.raises(OSError):run(ex)
    ex.place_limit_order_with_tpsl.assert_not_called()


def test_timeout_intent_is_adopted_by_client_oid_without_duplicate(cycle):
    ex,path,_=cycle;tm.write_tracker(path,{})
    ex.place_limit_order_with_tpsl.side_effect=TimeoutError('response lost')
    run(ex)
    state=tm.read_tracker(path)
    assert state['status']=='placement_unknown' and state['client_oid'].startswith('fb')
    ex.place_limit_order_with_tpsl.side_effect=None
    ex.fetch_order_by_client_oid.return_value={'id':'accepted','status':'open','filled':0}
    ex.fetch_order.return_value={'id':'accepted','status':'open','filled':0}
    run(ex)
    assert ex.place_limit_order_with_tpsl.call_count==1
    assert tm.read_tracker(path)['order_id']=='accepted'


def test_post_create_tracker_failure_recovers_by_client_oid(cycle,monkeypatch):
    ex,path,_=cycle;tm.write_tracker(path,{})
    real_write=tm.write_tracker;calls={'n':0}
    def flaky(path_arg,data):
        calls['n']+=1
        if calls['n']==2:raise OSError('after create')
        return real_write(path_arg,data)
    monkeypatch.setattr(tm,'write_tracker',flaky)
    with pytest.raises(OSError):run(ex)
    assert ex.place_limit_order_with_tpsl.call_count==1
    assert tm.read_tracker(path)['status']=='placing_entry'
    monkeypatch.setattr(tm,'write_tracker',real_write)
    ex.fetch_order_by_client_oid.return_value={'id':'accepted','status':'open','filled':0}
    ex.fetch_order.return_value={'id':'accepted','status':'open','filled':0}
    run(ex)
    assert ex.place_limit_order_with_tpsl.call_count==1


def test_client_oid_is_stable_bounded_and_changes_with_intent():
    first=entry_client_oid('confluence',SYMBOL,'15m','long',PLAN['b_ts'],'candle1',100,98,110,.5)
    same=entry_client_oid('confluence',SYMBOL,'15m','long',PLAN['b_ts'],'candle1',100,98,110,.5)
    changed=entry_client_oid('confluence',SYMBOL,'15m','long',PLAN['b_ts'],'candle2',100,98,110,.5)
    assert first==same and first!=changed and len(first)==32 and first.isalnum()


def _make_reconcile_due(path):
    state=tm.read_tracker(path);state['reconcile_after']='2000-01-01T00:00:00+00:00';tm.write_tracker(path,state)


def test_fill_requires_two_later_empty_checks_and_never_cancels_fresh_protection(cycle):
    ex,path,_=cycle;ex.fetch_order.return_value={'status':'closed','filled':1};ex.fetch_open_positions.return_value=[]
    run(ex)
    assert tm.read_tracker(path)['status']=='fill_reconcile'
    ex.cancel_all_orders_for_symbol.assert_not_called()
    _make_reconcile_due(path);run(ex)
    assert tm.read_tracker(path)['no_position_confirmations']==1
    ex.cancel_all_orders_for_symbol.assert_not_called()
    _make_reconcile_due(path);run(ex)
    ex.cancel_all_orders_for_symbol.assert_not_called()
    ex.place_limit_order_with_tpsl.assert_not_called()


def test_disappearing_open_position_is_confirmed_before_cleanup(cycle):
    ex,path,tracker=cycle;tracker['status']='open';tm.write_tracker(path,tracker);ex.fetch_open_positions.return_value=[]
    run(ex)
    assert tm.read_tracker(path)['status']=='position_reconcile'
    ex.cancel_all_orders_for_symbol.assert_not_called()
    _make_reconcile_due(path);run(ex)
    ex.cancel_all_orders_for_symbol.assert_not_called()
    _make_reconcile_due(path);run(ex)
    ex.cancel_all_orders_for_symbol.assert_called_once()
    ex.place_limit_order_with_tpsl.assert_not_called()


def test_strict_position_parser_never_turns_unknown_into_empty():
    ex=Exchange.__new__(Exchange);ex.markets={SYMBOL:{}};ex.exchange=MagicMock()
    ex.exchange.fetch_positions.return_value=[{'contracts':'not-a-number'}]
    assert ex.fetch_open_positions(SYMBOL)==[]
    with pytest.raises(RuntimeError):ex.fetch_open_positions(SYMBOL,strict=True)


def test_strict_position_parser_rejects_missing_size_fields():
    ex=Exchange.__new__(Exchange);ex.markets={SYMBOL:{}};ex.exchange=MagicMock()
    ex.exchange.fetch_positions.return_value=[{'symbol':SYMBOL}]
    assert ex.fetch_open_positions(SYMBOL)==[]
    with pytest.raises(RuntimeError):ex.fetch_open_positions(SYMBOL,strict=True)


@pytest.mark.parametrize('method',['fetch_open_orders','fetch_open_trigger_orders','fetch_position_tpsl_orders'])
def test_strict_order_queries_propagate_api_failure(method):
    ex=Exchange.__new__(Exchange);ex.markets={SYMBOL:{}};ex.exchange=MagicMock()
    ex.exchange.fetch_open_orders.side_effect=TimeoutError('api')
    assert getattr(ex,method)(SYMBOL)==[]
    with pytest.raises(TimeoutError):getattr(ex,method)(SYMBOL,strict=True)


def test_trigger_api_failure_cannot_spawn_repair_orders(tmp_path,monkeypatch):
    monkeypatch.setattr(tm,'TRACKER_DIR',str(tmp_path));monkeypatch.setattr(tm.time,'sleep',lambda *_:None)
    path=tm.get_tracker_path(SYMBOL,'15m')
    tm.write_tracker(path,dict(status='open',strategy='confluence',direction='long',b_ts=PLAN['b_ts'],
        sl_price=98.,tp1_price=110.))
    ex=MagicMock();ex.exchange.parse_timeframe.return_value=900
    ex.fetch_open_positions.return_value=[dict(side='long',contracts=1,entryPrice=100,unrealizedPnl=0)]
    ex.fetch_open_trigger_orders.side_effect=TimeoutError('trigger api')
    tm.full_trade_cycle(ex,CFG,{},logging.getLogger('test'))
    ex.fetch_open_trigger_orders.assert_called_once_with(SYMBOL,strict=True)
    ex.place_trigger_market_order.assert_not_called()


@pytest.mark.parametrize('field,value',[('sl_price',97.),('tp1_price',111.),('contracts',1.)])
def test_pending_protection_or_budget_change_forces_confirmed_replacement(cycle,field,value):
    ex,path,tracker=cycle
    tracker.update(candle_ts='2025-04-01T10:00:00+00:00',sl_price=98.,tp1_price=110.,contracts=.5)
    tracker[field]=value;tm.write_tracker(path,tracker)
    ex.fetch_order.side_effect=[{'status':'open','filled':0},{'status':'canceled','filled':0}]
    run(ex)
    ex.cancel_order.assert_called_once()
    ex.place_limit_order_with_tpsl.assert_called_once()


def test_pre_upgrade_keep_only_tracker_blocks_same_historical_impulse(cycle):
    ex,path,_=cycle;tm.write_tracker(path,{'notified_b_ts':PLAN['b_ts']})
    run(ex)
    ex.place_limit_order_with_tpsl.assert_not_called()
    assert tm.read_tracker(path)['execution_guard_version']==1
    assert consumed(tm._impulse_path(SYMBOL,'15m'),tm._impulse_key(PLAN))


def test_pre_upgrade_impulse_stays_blocked_when_first_upgrade_has_no_plan(cycle,monkeypatch):
    ex,path,_=cycle;tm.write_tracker(path,{'notified_b_ts':PLAN['b_ts']})
    plans=iter([None,dict(PLAN)])
    monkeypatch.setattr(logic,'plan_next_order',lambda *args:next(plans))
    run(ex);run(ex)
    ex.place_limit_order_with_tpsl.assert_not_called()
    for direction in ('long','short'):
        record=dict(PLAN,direction=direction)
        assert consumed(tm._impulse_path(SYMBOL,'15m'),tm._impulse_key(record))


def test_housekeeper_failure_is_not_reported_as_safe(cycle):
    ex,path,_=cycle;ex.cancel_all_orders_for_symbol.side_effect=TimeoutError('cancel api')
    assert tm.housekeeper_routine(ex,SYMBOL,path,logging.getLogger('test')) is False
    ex.fetch_open_positions.assert_not_called()


def _position_cycle_exchange():
    ex=MagicMock();ex.exchange.parse_timeframe.return_value=900
    ex.fetch_open_positions.return_value=[dict(side='long',contracts=1,entryPrice=100,unrealizedPnl=0)]
    ex.fetch_open_trigger_orders.return_value=[
        {'id':'new-sl','triggerPrice':98.}, {'id':'new-tp','triggerPrice':110.}]
    ex.fetch_position_tpsl_orders.return_value=[]
    ex.fetch_ticker.return_value={'last':100.}
    return ex


def _write_open_position_tracker(path):
    tm.write_tracker(path,dict(status='open',strategy='confluence',direction='long',b_ts=PLAN['b_ts'],
        sl_price=98.,tp1_price=110.,sl_order_id='stale-sl',tp_order_id='stale-tp'))


def test_existing_protection_by_price_prevents_duplicate_repair(tmp_path,monkeypatch):
    monkeypatch.setattr(tm,'TRACKER_DIR',str(tmp_path));monkeypatch.setattr(tm.time,'sleep',lambda *_:None)
    path=tm.get_tracker_path(SYMBOL,'15m');_write_open_position_tracker(path);ex=_position_cycle_exchange()
    tm.full_trade_cycle(ex,CFG,{},logging.getLogger('test'))
    ex.place_trigger_market_order.assert_not_called()


def test_overshoot_market_failure_keeps_protection_and_tracker(tmp_path,monkeypatch):
    monkeypatch.setattr(tm,'TRACKER_DIR',str(tmp_path));monkeypatch.setattr(tm.time,'sleep',lambda *_:None)
    path=tm.get_tracker_path(SYMBOL,'15m');_write_open_position_tracker(path);ex=_position_cycle_exchange()
    ex.fetch_ticker.return_value={'last':97.};ex.place_market_order.side_effect=TimeoutError('close timeout')
    tm.full_trade_cycle(ex,CFG,{},logging.getLogger('test'))
    ex.place_market_order.assert_called_once()
    ex.cancel_all_orders_for_symbol.assert_not_called()
    assert tm.read_tracker(path)['status']=='open'


def test_corrupt_candle_guard_cannot_disable_open_position_management(tmp_path,monkeypatch):
    monkeypatch.setattr(tm,'TRACKER_DIR',str(tmp_path));monkeypatch.setattr(tm.time,'sleep',lambda *_:None)
    path=tm.get_tracker_path(SYMBOL,'15m');_write_open_position_tracker(path)
    Path(tm._candle_guard_path(SYMBOL,'15m')).write_text('broken',encoding='utf-8')
    ex=_position_cycle_exchange();tm.full_trade_cycle(ex,CFG,{},logging.getLogger('test'))
    ex.fetch_open_trigger_orders.assert_called_once_with(SYMBOL,strict=True)
    ex.place_trigger_market_order.assert_not_called()
