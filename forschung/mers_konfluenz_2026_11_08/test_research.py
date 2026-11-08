import unittest
import numpy as np
import pandas as pd
import run as R


class ResearchChecks(unittest.TestCase):
    def frame(self):
        return pd.DataFrame({'open':[100.,100.,100.,100.,100.,100.],
            'high':[101.,101.,101.,111.,101.,101.],
            'low':[99.,99.,99.,89.,99.,99.],
            'close':[100.,100.,100.,100.,100.,100.]},
            index=pd.date_range('2025-01-01',periods=6,freq='4h',tz='UTC'))

    def event(self,i=2):
        return dict(i=i,limit=100.,sl=90.,tp=110.)

    def test_ambiguous_bar_sl_first_and_fees(self):
        df=self.frame()
        t=R.simulate(df,{1:[self.event()],-1:[]},'L')[0]
        self.assertEqual(t['res'],'sl')
        xp=90.-.0002*90.
        self.assertAlmostEqual(t['R'],(xp-100.-.0006*(100.+xp))/10.)

    def test_confirmation_next_open_not_touch_price(self):
        df=self.frame();df.loc[df.index[2],'close']=101.
        df.loc[df.index[3],['open','high','low']]=[102.,104.,101.]
        df.loc[df.index[4],['high','low']]=[121.,99.]
        event={**self.event(),'tp':120.}
        t=R.simulate(df,{1:[event],-1:[]},'C')[0]
        self.assertEqual(t['entry_ts'],df.index[3])
        self.assertEqual(t['res'],'tp')
        ep=102.*1.0002
        self.assertAlmostEqual(t['R'],(120.-ep-.0006*(ep+120.))/(ep-90.))

    def test_stop_before_confirmation_invalidates(self):
        df=self.frame();df.loc[df.index[2],['low','close']]=[89.,101.]
        self.assertEqual(R.simulate(df,{1:[self.event()],-1:[]},'C'),[])

    def test_mirror_symmetry(self):
        df=self.frame()
        mirrored=pd.DataFrame(dict(open=-df.open,high=-df.low,low=-df.high,close=-df.close),index=df.index)
        a=R.simulate(df,{1:[self.event()],-1:[]},'L')
        b=R.simulate(mirrored,{1:[],-1:[self.event()]},'L')
        self.assertAlmostEqual(a[0]['R'],b[0]['R'])

    def test_features_do_not_change_when_future_appended(self):
        rng=np.random.default_rng(31)
        c=100.+np.cumsum(rng.normal(0,.3,150))
        full=R.features(c+1,c-1,c)
        part=R.features(c[:90]+1,c[:90]-1,c[:90])
        for x,y in zip(full,part): np.testing.assert_array_equal(x[:90],y)

    def test_falling_price_energy_does_not_confirm_long(self):
        c=1000.-np.arange(50,dtype=float)**2/10
        _,energy,_=R.features(c+1,c-1,c)
        self.assertFalse(energy.any())

    def test_pressure_requires_previous_selling(self):
        c=100.+np.arange(50,dtype=float)/10
        pressure,_,_=R.features(c+1,c-1,c)
        self.assertFalse(pressure.any())

    def test_trade_gap_excluded(self):
        df=self.frame();df.index=df.index[:3].append(df.index[3:]+pd.Timedelta(hours=4))
        self.assertEqual(R.simulate(df,{1:[self.event()],-1:[]},'L'),[])

    def test_unclosed_trade_excluded(self):
        df=self.frame();df['high']=101.;df['low']=99.
        self.assertEqual(R.simulate(df,{1:[self.event()],-1:[]},'L'),[])

    def test_unclosed_trade_still_blocks_later_entries(self):
        df=self.frame()
        long=dict(i=2,limit=100.,sl=80.,tp=200.)
        short=dict(i=3,limit=-100.,sl=-110.,tp=-90.)
        self.assertEqual(R.simulate(df,{1:[long],-1:[short]},'L'),[])

    def test_gap_stop_at_worse_open(self):
        df=self.frame()
        df.loc[df.index[3],['open','high','low','close']]=[85.,86.,84.,85.]
        t=R.simulate(df,{1:[self.event()],-1:[]},'L')[0]
        xp=85.*.9998
        self.assertAlmostEqual(t['R'],(xp-100.-.0006*(100.+xp))/10.)

    def test_opposite_sides_share_position_limit(self):
        df=self.frame()
        short=dict(i=2,limit=-100.,sl=-110.,tp=-90.)
        t=R.simulate(df,{1:[self.event()],-1:[short]},'L')
        self.assertEqual(len(t),1)


if __name__=='__main__': unittest.main()
