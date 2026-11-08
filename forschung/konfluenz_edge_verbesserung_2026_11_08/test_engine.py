import unittest
import numpy as np
import pandas as pd
from engine import find_exit,candidates,outcome,isolated,portfolio,FEE,SLIP

class EngineTests(unittest.TestCase):
    def frame(self):
        idx=pd.date_range('2026-01-01',periods=30,freq='h',tz='UTC')
        df=pd.DataFrame(dict(open=100.,high=101.,low=99.,close=100.,_sig_dir=0,
                     _sig_entry=100.,_sig_sl=95.,_sig_tp1=110.),index=idx)
        df.loc[idx[20],'_sig_dir']=1
        return df

    def cfg(self,symbol='TEST/USDT:USDT'):
        return dict(market=dict(symbol=symbol,timeframe='1h'),risk=dict(leverage=3,risk_per_entry_pct=1))

    def test_stop_first_and_no_entry_target(self):
        j,p,k=find_exit(np.array([100.,100.]),np.array([120.,120.]),np.array([90.,99.]),0,100,95,110,1)
        self.assertEqual((j,k),(0,'sl'));self.assertAlmostEqual(p,95*(1-SLIP))
        j,p,k=find_exit(np.array([100.,100.]),np.array([120.,120.]),np.array([99.,99.]),0,100,95,110,1)
        self.assertEqual((j,k),(1,'tp'))

    def test_gap_and_short_symmetry(self):
        j,p,k=find_exit(np.array([100.,90.]),np.array([101.,92.]),np.array([99.,88.]),0,100,95,110,1)
        self.assertAlmostEqual(p,90*(1-SLIP))
        j,p,k=find_exit(np.array([100.,110.]),np.array([101.,112.]),np.array([99.,108.]),0,100,105,90,-1)
        self.assertEqual(k,'sl');self.assertAlmostEqual(p,110*(1+SLIP))

    def test_confirmation_waits_for_close_then_next_open(self):
        df=self.frame();df.iloc[20,df.columns.get_loc('close')]=100.5
        df.iloc[21,df.columns.get_loc('open')]=101
        rows=candidates(df,self.cfg(),'C_S_R20',lambda s,t:True)
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['entry_ts'],df.index[21])
        self.assertAlmostEqual(rows[0]['entry'],101*(1+SLIP))
        self.assertAlmostEqual(rows[0]['tp']-rows[0]['entry'],2*rows[0]['risk'])
        df.iloc[20,df.columns.get_loc('low')]=94
        self.assertEqual(candidates(df,self.cfg(),'C_S_R20'),[])

    def test_confirmation_rechecks_trend(self):
        df=self.frame();df.loc[df.index[20],'close']=100.5
        self.assertEqual(candidates(df,self.cfg(),'C_S_R20',lambda s,t:False),[])

    def test_atr_stop_only_widens_and_uses_prior_candles(self):
        df=self.frame();df['_sig_sl']=99.5
        a=candidates(df,self.cfg(),'L_A2_R20')[0]
        self.assertAlmostEqual(a['sl'],96.)
        df.loc[df.index[20],['high','low']]=[200.,50.]
        b=candidates(df,self.cfg(),'L_A2_R20')[0]
        self.assertEqual(a['sl'],b['sl'])
        df['_sig_sl']=90.
        self.assertEqual(candidates(df,self.cfg(),'L_A2_R20')[0]['sl'],90.)

    def test_future_exit_censored_and_positions_blocked(self):
        df=self.frame();df.loc[df.index[25],'high']=111
        rows=candidates(df,self.cfg(),'L_S_K');row=rows[0]
        end=df.index[24]
        done,r,t,p=outcome(row,end,df)
        self.assertFalse(done);self.assertEqual(t,end);self.assertEqual(p,100.)
        self.assertAlmostEqual(r,-2*FEE*100/5)
        self.assertLess(outcome(row,end,df,True)[1],r)
        extra={**row,'entry_ts':df.index[22],'touch_ts':df.index[22]}
        closed,opens,equity=isolated([row,extra],df,self.cfg(),df.index[0],end)
        self.assertEqual((len(closed),len(opens)),(0,1));self.assertEqual(equity,60)

    def test_portfolio_limits_and_risk_sizing(self):
        df=self.frame();df.loc[df.index[25],'high']=111
        row=candidates(df,self.cfg(),'L_S_K')[0]
        cfgs={'a':self.cfg(),'b':self.cfg('OTHER/USDT:USDT')}
        summary,ledger,curve=portfolio({'a':[row],'b':[row]},{'a':df,'b':df},cfgs,df.index[0],df.index[-1],max_positions=1)
        self.assertEqual(summary['closed'],1);self.assertEqual(summary['open_end'],0)
        self.assertAlmostEqual(ledger.pnl.iloc[0],.6*row['net_r'])
        self.assertAlmostEqual(summary['end_equity'],60+ledger.pnl.sum())
        summary,ledger,_=portfolio({'a':[row],'b':[row]},{'a':df,'b':df},{'a':self.cfg(),'b':self.cfg()},df.index[0],df.index[-1])
        self.assertEqual(summary['closed'],1)

if __name__=='__main__':unittest.main()
