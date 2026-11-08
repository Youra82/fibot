import contextlib
import io
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
import pandas as pd
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fibot.analysis import analysis_suite as S


class EdgeAnalysisTests(TestCase):
    def test_actual_net_r_comes_from_pnl_and_contract_risk(self):
        trade=SimpleNamespace(result='win',entry=100.,sl=90.,direction='long',
            exit_price=120.,contracts=10.,pnl_usdt=180.,pnl_pct=18.,exit_bar=1,
            timestamp=pd.Timestamp('2026-01-01',tz='UTC'))
        frame=pd.DataFrame(index=pd.date_range('2026-01-01',periods=2,tz='UTC'))
        t=S.trades_frame(SimpleNamespace(trades=[trade]),frame)
        self.assertAlmostEqual(t.r_actual.iloc[0],1.8)
        self.assertAlmostEqual(t.risk_usdt.iloc[0],100.)
        self.assertAlmostEqual(t.r_gross.iloc[0]-t.r_actual.iloc[0],.2)

    def test_analysis_uses_net_r_and_preserves_config(self):
        times=pd.date_range('2025-01-01',periods=4,freq='90D',tz='UTC')
        t=pd.DataFrame(dict(ts=times,exit_ts=times,r_actual=[2.,-1.,2.,-1.],
                            r=[999.]*4,r_gross=[2.1,-.9,2.1,-.9]))
        cfg={'market':{'symbol':'BTC/USDT:USDT','timeframe':'1h'},'risk':{'risk_per_entry_pct':1.}}
        sample={'one':{'cfg':cfg,'trades':t}}
        a=SimpleNamespace(date_from='2025-01-01',date_to='2026-01-01',capital=100.)
        S._LINES.clear()
        with patch.object(S,'backtest_all',return_value=sample),contextlib.redirect_stdout(io.StringIO()):
            S.a13_edge_math({},a)
        report='\n'.join(S._LINES)
        self.assertIn('Netto-Erwartung +0.5000',report)
        self.assertIn('Kosten 0.1000',report)
        self.assertEqual(cfg['risk']['risk_per_entry_pct'],1.)

    def test_empty_trade_results_are_safe(self):
        a=SimpleNamespace(date_from='',date_to='',capital=100.)
        with patch.object(S,'backtest_all',return_value={'x':{'trades':pd.DataFrame()}}),contextlib.redirect_stdout(io.StringIO()):
            S.a13_edge_math({},a)

    def test_kelly_analysis_uses_loss_size_in_r(self):
        t=pd.DataFrame({'r_actual':[2.]*6+[-2.]*4})
        cfg={'market':{'symbol':'BTC/USDT:USDT','timeframe':'1h'},'risk':{'risk_per_entry_pct':1.}}
        a=SimpleNamespace(date_from='',date_to='',capital=100.)
        S._LINES.clear()
        with patch.object(S,'backtest_all',return_value={'x':{'trades':t,'cfg':cfg}}),contextlib.redirect_stdout(io.StringIO()):
            S.a10_kelly({},a)
        self.assertIn('10.00%', '\n'.join(S._LINES))
        self.assertEqual(cfg['risk']['risk_per_entry_pct'],1.)
