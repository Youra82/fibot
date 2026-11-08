import sys
from pathlib import Path
import unittest
import numpy as np
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fibot.analysis.edge_math import edge_metrics,growth_metrics,empirical_log_optimum,recovery_required,block_bootstrap

class EdgeMathTests(unittest.TestCase):
    def test_expectancy_and_payoff(self):
        r=edge_metrics([2,2,-1,-1,-1])
        self.assertAlmostEqual(r['expectancy_r'],.2)
        self.assertAlmostEqual(r['payoff'],2)
        self.assertAlmostEqual(r['break_even_win_rate'],1/3)
        self.assertAlmostEqual(r['profit_factor'],4/3)

    def test_zero_outcomes_change_total_breakeven_rate(self):
        r=edge_metrics([2,-1,0,0])
        self.assertAlmostEqual(r['break_even_win_rate'],1/6)
        self.assertEqual(r['breakeven'],2)

    def test_costs_can_destroy_gross_edge(self):
        r=edge_metrics([.8,-1.2],gross_r=[1,-1])
        self.assertAlmostEqual(r['mean_cost_r'],.2)
        self.assertLess(r['expectancy_r'],0)

    def test_positive_arithmetic_can_have_negative_growth(self):
        g=growth_metrics([1,-.8],.5)
        self.assertGreater(g['arithmetic_trade_return'],0)
        self.assertLess(g['mean_log_growth'],0)
        self.assertAlmostEqual(g['total_return'],-.1)

    def test_drawdown_includes_initial_capital(self):
        self.assertAlmostEqual(growth_metrics([-1,1],.1)['max_drawdown'],.1)

    def test_insolvency_is_not_silently_clipped(self):
        self.assertTrue(growth_metrics([-2,3],.5)['insolvent'])

    def test_recovery_is_asymmetric(self):
        self.assertAlmostEqual(recovery_required(.5),1)
        self.assertAlmostEqual(recovery_required(.2),.25)

    def test_empirical_optimum_uses_actual_r_units(self):
        # Equal chances +2R/-2R: optimum zero, not an arbitrary positive Kelly.
        self.assertEqual(empirical_log_optimum([2,-2]),0)
        # p=.6, +/-2R: optimum risk budget f=.1 (loss costs 2R).
        self.assertAlmostEqual(empirical_log_optimum([2,2,2,-2,-2]),.1,places=7)

    def test_invalid_inputs_rejected(self):
        for x in ([],[np.nan],[np.inf]):
            with self.assertRaises(ValueError):edge_metrics(x)
        with self.assertRaises(ValueError):growth_metrics([1],-.1)
        with self.assertRaises(ValueError):recovery_required(1)

    def test_short_history_has_no_fake_confidence(self):
        r=block_bootstrap([1,-1],pd.to_datetime(['2026-01-01','2026-01-02']),.01)
        self.assertIsNone(r['expectancy_ci'])

    def test_block_bootstrap_reproducible_and_sign(self):
        t=pd.date_range('2025-01-01',periods=12,freq='28D',tz='UTC')
        a=block_bootstrap([-1]*12,t,.01,samples=100)
        b=block_bootstrap([-1]*12,t,.01,samples=100)
        self.assertEqual(a,b);self.assertEqual(a['loss_fraction'],1)
        self.assertEqual(a['expectancy_ci'],[-1.,-1.])

    def test_series_timestamps_supported(self):
        t=pd.Series(pd.date_range('2025-01-01',periods=12,freq='28D',tz='UTC'))
        r=block_bootstrap([1,-1]*6,t,.01,samples=100)
        self.assertIsNotNone(r['expectancy_ci'])

if __name__=='__main__':unittest.main()
