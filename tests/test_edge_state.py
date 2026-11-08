import sys
from pathlib import Path
import unittest
import numpy as np
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fibot.analysis.edge_state import market_states,attach_states,frontier_point,uncertainty,rolling_points
from fibot.analysis.edge_dashboard import complete_days


def daily(n=360):
    index=pd.date_range('2024-01-01',periods=n,tz='UTC')
    close=100+np.arange(n)*.2+np.sin(np.arange(n)/9)
    return pd.DataFrame(dict(open=close,high=close+2,low=close-2,close=close),index=index)


class EdgeStateTests(unittest.TestCase):
    def test_future_append_does_not_change_past_regimes(self):
        full=daily();part=market_states(full.iloc[:250]);all_states=market_states(full)
        pd.testing.assert_frame_equal(part,all_states.iloc[:250])

    def test_day_is_only_available_next_day(self):
        d=daily();s=market_states(d)
        self.assertEqual(s.index[200],d.index[200]+pd.Timedelta(days=1))
        t=pd.DataFrame({'entry_ts':[s.index[200]-pd.Timedelta(seconds=1),s.index[200]]})
        q=attach_states(t,s)
        self.assertEqual(q.trend.iloc[0],s.trend.iloc[199])
        self.assertEqual(q.trend.iloc[1],s.trend.iloc[200])

    def test_before_history_is_unknown(self):
        s=market_states(daily())
        t=pd.DataFrame({'entry_ts':[s.index[0]-pd.Timedelta(hours=1)]})
        self.assertEqual(attach_states(t,s).trend.iloc[0],'unknown')

    def test_volatility_threshold_uses_previous_days(self):
        d=daily();d.loc[d.index[200],['high','low']]=[200.,1.]
        s=market_states(d)
        self.assertEqual(s.volatility.iloc[200],'high')
        self.assertEqual(s.volatility.iloc[20],'unknown')

    def test_zeros_do_not_break_fixed_frontier(self):
        p=frontier_point([2,-1,0,0])
        self.assertEqual(p['x'],2)
        self.assertEqual(p['y'],.5)
        self.assertEqual(p['metrics']['expectancy_r'],.25)

    def test_one_sided_results_have_no_payoff(self):
        self.assertIsNone(frontier_point([1,2,3])['x'])
        self.assertIsNone(frontier_point([0,0])['y'])

    def test_sparse_blocks_cannot_fake_evidence(self):
        t=[pd.Timestamp('2025-01-01',tz='UTC')]*15+[pd.Timestamp('2025-12-01',tz='UTC')]*15
        r=uncertainty([1,-1]*15,t)
        self.assertEqual(r['status'],'insufficient')
        self.assertEqual(r['nonempty_blocks'],2)

    def test_joint_bootstrap_is_reproducible(self):
        t=pd.date_range('2025-01-01',periods=60,freq='3D',tz='UTC')
        r=[2,-1]*30
        a=uncertainty(r,t,samples=150);b=uncertainty(r,t,samples=150)
        self.assertEqual(a,b)
        self.assertEqual(a['status'],'positive')
        self.assertGreater(len(a['cloud']),0)

    def test_rolling_points_never_use_later_trades(self):
        t=pd.DataFrame({'known_at':pd.date_range('2025-01-01',periods=80,tz='UTC'),'net_r':[2,-1]*40})
        a=rolling_points(t.iloc[:60]);b=rolling_points(t)
        self.assertEqual(a,b[:len(a)])
        self.assertEqual(a[0]['known_at'],t.known_at.iloc[49].isoformat())

    def test_intraday_day_requires_all_bars(self):
        idx=pd.date_range('2026-01-01',periods=48,freq='h',tz='UTC')
        d=pd.DataFrame(dict(open=1.,high=2.,low=.5,close=1.5),index=idx)
        self.assertEqual(len(complete_days(d,'1h')),2)
        self.assertEqual(len(complete_days(d.drop(idx[10]),'1h')),1)
        self.assertTrue(complete_days(d.iloc[:23],'1h').empty)

    def test_invalid_daily_inputs_rejected(self):
        d=daily();d.index=d.index.tz_localize(None)
        with self.assertRaises(ValueError):market_states(d)
        d=daily();d.iloc[0,1]=np.nan
        with self.assertRaises(ValueError):market_states(d)

if __name__=='__main__':unittest.main()
