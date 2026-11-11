import datetime as dt
import unittest

from bot import backtest
from tests.helpers import breakout_day, cfg, flat_day


class TestBacktest(unittest.TestCase):
    def test_target_trade_with_costs(self):
        after = [(101.5, 101.6, 101.4, 101.5), (101.5, 104, 101.5, 103.9)] + [(104, 104, 104, 104)] * 72
        c = cfg(slippage_bps=10, sell_fee_bps=0, max_position_usd=100000)
        t = backtest.run({"X": breakout_day(after=after)}, c)[0]
        # entry at the 9:50 open 101.5 + 0.1% = 101.6015; risk 1.6015 -> 31 shares
        self.assertEqual((t["entry_time"], t["qty"], t["reason"]), ("09:50", 31, "target"))
        self.assertEqual(t["target"], 103.2)
        self.assertAlmostEqual(t["pnl"], round((103.2 - 101.6015) * 31, 2))
        self.assertLess(t["pnl"], t["gross_pnl"])

    def test_costs_turn_flat_trade_negative(self):
        t = backtest.run({"X": breakout_day()}, cfg())[0]
        self.assertEqual(t["reason"], "flat")
        self.assertLess(t["pnl"], t["gross_pnl"])

    def test_max_trades_per_day_across_symbols(self):
        bars = {s: breakout_day() for s in "ABCDE"}
        trades = backtest.run(bars, cfg(max_position_usd=1000))
        self.assertEqual([t["symbol"] for t in trades], ["A", "B", "C"])

    def test_no_signal_no_trade_and_summary(self):
        self.assertEqual(backtest.run({"X": flat_day()}, cfg()), [])
        d1 = breakout_day(dt.date(2025, 3, 3))
        d2 = breakout_day(dt.date(2025, 3, 4), after=[(101.5, 101.5, 99, 99.5)] + [(99.5,) * 4] * 73)
        s = backtest.summarize(backtest.run({"X": d1 + d2}, cfg()), cfg())
        self.assertEqual((s["trades"], s["exits"]), (2, {"flat": 1, "stop": 1}))
        self.assertLess(s["max_drawdown"], 0)


if __name__ == "__main__":
    unittest.main()
