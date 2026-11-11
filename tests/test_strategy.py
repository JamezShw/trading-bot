import unittest

from bot import strategy
from bot.risk import DayRisk
from tests.helpers import breakout_day, cfg, day, flat_day


class TestSignal(unittest.TestCase):
    def test_opening_range(self):
        self.assertEqual(strategy.opening_range(breakout_day(), cfg()), (101, 99))

    def test_close_above_range_triggers(self):
        s = strategy.find_signal("X", breakout_day(), cfg())
        self.assertEqual(s.bar_index, 3)
        self.assertEqual(s.stop, 100.0)
        self.assertEqual(s.bar.t.strftime("%H:%M"), "09:45")

    def test_wick_above_is_not_a_trigger(self):
        bars = breakout_day(after=[])
        bars[3] = bars[3]._replace(h=102, c=100.9)
        self.assertIsNone(strategy.find_signal("X", bars, cfg()))

    def test_close_equal_to_high_is_not_above(self):
        bars = breakout_day(after=[])
        bars[3] = bars[3]._replace(c=101.0)
        self.assertIsNone(strategy.find_signal("X", bars, cfg()))

    def test_no_signal_after_entry_cutoff(self):
        # range bars, then flat until 15:30, then a breakout at 15:30 (closes 15:35)
        p = [(100, 101, 99, 100)] * 3 + [(100, 100.5, 99.5, 100)] * 69 + [(100, 102, 100, 101.8)]
        self.assertIsNone(strategy.find_signal("X", day(p), cfg()))

    def test_incomplete_range_gives_nothing(self):
        self.assertIsNone(strategy.find_signal("X", breakout_day()[1:], cfg()))

    def test_closed_through_hides_future_bars(self):
        self.assertIsNone(strategy.find_signal("X", breakout_day(), cfg(), closed_through=2))


class TestSizing(unittest.TestCase):
    def test_reel_example(self):
        # day-trader-skill's TSLA example: $50 max loss, 5.86 risk a share -> 8 shares
        self.assertEqual(strategy.size(364.18, 358.32, cfg(), 10000), 8)

    def test_capped_by_position_and_cash(self):
        self.assertEqual(strategy.size(100, 99.9, cfg(), 10000), 40)   # $4,000 cap
        self.assertEqual(strategy.size(100, 99.9, cfg(), 1500), 15)    # cash

    def test_plan_rejects_entry_at_or_below_stop(self):
        s = strategy.find_signal("X", breakout_day(), cfg())
        self.assertIsNone(strategy.make_plan(s, 100.0, cfg(), 5000))
        p = strategy.make_plan(s, 101.5, cfg(), 5000)
        self.assertEqual((p.qty, p.stop, p.target), (33, 100.0, 103.0))


class TestExit(unittest.TestCase):
    def plan(self):
        s = strategy.find_signal("X", breakout_day(), cfg())
        return strategy.make_plan(s, 101.5, cfg(), 5000)

    def test_bar_hitting_both_counts_as_stop(self):
        bars = breakout_day(after=[(101.5, 103.5, 99.5, 102)])
        self.assertEqual(strategy.simulate_exit(bars, 4, self.plan(), cfg())[:2], (100.0, "stop"))

    def test_gap_through_stop_fills_at_open(self):
        bars = breakout_day(after=[(101.5, 101.6, 101.4, 101.5), (98, 98.5, 97, 98)])
        self.assertEqual(strategy.simulate_exit(bars, 4, self.plan(), cfg())[:2], (98, "stop"))

    def test_target(self):
        bars = breakout_day(after=[(101.5, 103.2, 101.4, 103)])
        self.assertEqual(strategy.simulate_exit(bars, 4, self.plan(), cfg())[:2], (103.0, "target"))

    def test_flat_by_close(self):
        px, why, bar = strategy.simulate_exit(breakout_day(), 4, self.plan(), cfg())
        self.assertEqual((why, bar.t.strftime("%H:%M")), ("flat", "15:55"))


class TestDayRisk(unittest.TestCase):
    def test_limits(self):
        r = DayRisk(cfg())
        self.assertFalse(r.allows(60)[0])               # over $50 per trade
        for s in "ABC":
            self.assertTrue(r.allows(50)[0])
            r.opened(s, 50)
        self.assertIn("trades per day", r.allows(10)[1])

    def test_daily_loss_counts_open_risk(self):
        r = DayRisk(cfg())
        r.opened("A", 50)
        r.closed("A", -110)
        self.assertFalse(r.allows(45)[0])               # 110 + 45 > 150
        self.assertTrue(r.allows(40)[0])
        r.closed("B", -40)
        self.assertIsNotNone(r.halted)


if __name__ == "__main__":
    unittest.main()
