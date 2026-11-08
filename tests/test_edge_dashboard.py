import sys
from pathlib import Path
import contextlib
import tempfile
import io
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import json
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fibot.analysis import edge_dashboard as D,analysis_suite as S
from fibot.strategy import confluence_logic as C,trend_filter as F
from fibot.analysis import backtester as B


class EdgeDashboardTests(unittest.TestCase):
    def test_invalid_capital_rejected_before_backtest(self):
        for capital in (0,-1,float('nan')):
            with self.assertRaises(ValueError):D.generate({},'2026-05-10','2026-11-08',capital)

    def test_invalid_period_rejected_before_backtest(self):
        with self.assertRaises(ValueError):D.generate({},'2026-11-08','2026-05-10')

    def test_snapshot_serializes_empty_history(self):
        columns=['entry_ts','exit_ts','known_at','net_r','gross_r','coin','tf','direction','config','pnl']
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'edge.html'
            data=D.write_dashboard(pd.DataFrame(columns=columns),pd.DataFrame(),out,
                dict(as_of='2026-11-08T00:00:00+00:00',start='2026-05-10T00:00:00+00:00'))
            self.assertEqual(data['trades'],[])
            self.assertTrue(out.exists())
            self.assertNotIn('__DATA__',out.read_text(encoding='utf8'))

    def test_no_result_visible_before_exit_bar_closed(self):
        t=pd.DataFrame([dict(entry_ts=pd.Timestamp('2026-01-01',tz='UTC'),
            exit_ts=pd.Timestamp('2026-01-02',tz='UTC'),known_at=pd.Timestamp('2026-01-02 01:00',tz='UTC'),
            net_r=2.,gross_r=2.1,coin='BTC',tf='1h',direction='long',config='x',pnl=1.)])
        with tempfile.TemporaryDirectory() as tmp:
            data=D.write_dashboard(t,pd.DataFrame(),Path(tmp)/'edge.html',
                 dict(as_of='2026-01-02T00:30:00+00:00',start='2026-01-01T00:00:00+00:00'))
            self.assertEqual(data['trades'],[])

    def test_warmup_does_not_trade_before_start(self):
        idx=pd.date_range('2024-01-01',periods=1500,freq='h',tz='UTC')
        raw=pd.DataFrame(dict(open=100.,high=101.,low=99.,close=100.,volume=1.),index=idx)
        start=idx[1200]
        cfg={'market':{'symbol':'BTC/USDT:USDT','timeframe':'1h'},'strategy':{'type':'confluence'}}
        def prepare(df,cfg):
            out=df.copy();out['_sig_dir']=1;out['_sig_instant']=False;return out
        def run(df,*args):
            self.assertTrue((df.loc[df.index<start,'_sig_dir']==0).all())
            self.assertTrue((df.loc[df.index>=start,'_sig_dir']==1).all())
            return SimpleNamespace(trades=[])
        with patch.object(D,'read_cache',return_value=raw),patch.object(F,'settings',return_value={'enabled':False}),patch.object(C,'precompute_confluence_signals',side_effect=prepare),patch.object(B,'run_backtest',side_effect=run):
            t,coverage=D.collect_backtests({'x':cfg},'.',start,idx[-1]+pd.Timedelta(hours=1))
        self.assertTrue(t.empty);self.assertEqual(coverage[0]['status'],'ok')

    def test_menu14_is_registered(self):
        self.assertIs(S.ANALYSES[14],S.a14_edge_dashboard)
        args=SimpleNamespace(date_from='2026-05-10',date_to='2026-11-08',capital=60.)
        with patch.object(D,'generate',return_value=(Path('edge.html'),{'trades':[]})) as gen,contextlib.redirect_stdout(io.StringIO()):
            S.a14_edge_dashboard({},args)
        gen.assert_called_once()

if __name__=='__main__':unittest.main()
