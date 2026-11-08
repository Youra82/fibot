import unittest
import numpy as np
import pandas as pd
import run as R

class FilterChecks(unittest.TestCase):
    def test_one_coin_across_timeframes(self):
        ts=pd.date_range('2025-01-01',periods=4,freq='h',tz='UTC')
        t=pd.DataFrame({'coin':['A','A','B','A'],'ts':ts,
                        'exit_ts':[ts[2],ts[3],ts[3],ts[3]],'tf':['1h','15m','1h','1h']})
        kept=R.replay(t,np.ones(4,dtype=bool))
        self.assertEqual(list(kept.index),[0,2,3])

    def test_filtered_trade_does_not_reserve_position(self):
        ts=pd.date_range('2025-01-01',periods=3,freq='h',tz='UTC')
        t=pd.DataFrame({'coin':['A','A'],'ts':ts[:2],'exit_ts':[ts[2],ts[2]]})
        self.assertEqual(list(R.replay(t,np.array([False,True])).index),[1])

    def test_exit_at_same_timestamp_still_blocks_entry(self):
        ts=pd.date_range('2025-01-01',periods=3,freq='h',tz='UTC')
        t=pd.DataFrame({'coin':['A','A'],'ts':ts[:2],'exit_ts':[ts[1],ts[2]]})
        self.assertEqual(list(R.replay(t,np.array([True,True])).index),[0])

    def test_rules_reject_unknown_features(self):
        t=pd.DataFrame({'ema_ok':[True,True],'slope_ok':[True,True],
                        'stop_atr':[2.,2.],'rr':[2.,2.],'vol_ratio':[2.,2.],
                        'adx':[30.,30.],'rsi':[50.,50.],'eligible':[True,False]})
        for k,m in R.masks(t).items():
            self.assertFalse(m[1],k)

if __name__=='__main__':unittest.main()
