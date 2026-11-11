import datetime as dt
import os
import tempfile
import unittest

from bot import alpaca, live
from bot.bars import NY
from tests.helpers import breakout_day, cfg

DAY = dt.date(2025, 3, 3)


def at(hhmm):
    h, m = map(int, hhmm.split(":"))
    return dt.datetime(2025, 3, 3, h, m, 20, tzinfo=NY)


def raw(bars):
    return [{"t": b.t.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
             "o": b.o, "h": b.h, "l": b.l, "c": b.c, "v": b.v} for b in bars]


class FakeAlpaca:
    paper = True

    def __init__(self, bars_by_symbol, equity=5000.0, open_today=True):
        self.data = {s: raw(b) for s, b in bars_by_symbol.items()}
        self.equity, self.open_today = equity, open_today
        self.orders, self.canceled, self.closed = [], [], []
        self.held = {"OTHER": {"symbol": "OTHER", "unrealized_pl": "0", "cost_basis": "500"}}

    def calendar(self, start, end):
        return [{"date": start, "open": "09:30", "close": "16:00"}] if self.open_today else []

    def account(self):
        return {"equity": str(self.equity), "last_equity": "5000", "cash": "5000"}

    def positions(self):
        return list(self.held.values())

    def bars(self, symbols, start, end, feed):
        end_t = dt.datetime.fromisoformat(end)
        return {s: [r for r in self.data.get(s, [])
                    if dt.datetime.fromisoformat(r["t"].replace("Z", "+00:00")) < end_t] for s in symbols}

    def bracket_buy(self, symbol, qty, stop, target, client_order_id):
        self.orders.append((symbol, qty, stop, target))
        self.held[symbol] = {"symbol": symbol, "unrealized_pl": "0", "cost_basis": str(qty * 101.5)}
        return {"id": "o%d" % len(self.orders)}

    def open_orders(self, symbols=None):
        return [{"id": "leg-" + s} for s in symbols or []]

    def cancel_order(self, oid):
        self.canceled.append(oid)

    def close_position(self, symbol):
        self.closed.append(symbol)
        self.held.pop(symbol, None)


class TestTrader(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.c = cfg(watchlist=["AAA", "BBB"])
        self.fake = FakeAlpaca({"AAA": breakout_day(), "BBB": breakout_day()[:3]})
        self.t = live.Trader(self.c, self.fake, self.dir, log=lambda *a: None, settle_seconds=0)

    def test_does_nothing_unless_armed_today(self):
        self.assertEqual(self.t.tick(at("09:50")), "waiting for you to arm today")
        live.arm(self.dir, DAY - dt.timedelta(days=1))           # yesterday's arm does not count
        self.assertEqual(self.t.tick(at("09:50")), "waiting for you to arm today")
        self.assertEqual(self.fake.orders, [])

    def test_buys_fresh_breakout_once(self):
        live.arm(self.dir, DAY)
        self.assertEqual(self.t.tick(at("09:45")), "watching")   # 9:45 bar not closed yet
        self.assertEqual(self.fake.orders, [])
        self.t.tick(at("09:50"))
        self.assertEqual(self.fake.orders, [("AAA", 33, 100.0, 103.0)])
        self.t.tick(at("09:55"))
        self.assertEqual(len(self.fake.orders), 1)

    def test_missed_breakout_is_not_chased(self):
        live.arm(self.dir, DAY)
        self.t.tick(at("10:30"))                                 # armed after the 9:45 breakout
        self.assertEqual(self.fake.orders, [])

    def test_flattens_only_its_own_positions_and_disarms(self):
        live.arm(self.dir, DAY)
        self.t.tick(at("09:50"))
        self.assertEqual(self.t.tick(at("15:55")), "done for today")
        self.assertEqual((self.fake.canceled, self.fake.closed), (["leg-AAA"], ["AAA"]))
        self.assertIn("OTHER", self.fake.held)
        self.assertFalse(live.armed_for(self.dir, DAY))

    def test_kill_switch(self):
        live.arm(self.dir, DAY)
        self.t.tick(at("09:50"))
        live.request_stop(self.dir)
        self.assertEqual(self.t.tick(at("10:00")), "stopped")
        self.assertEqual(self.fake.closed, ["AAA"])

    def test_daily_loss_halts_new_trades(self):
        self.fake.equity = 4840.0
        live.arm(self.dir, DAY)
        self.assertTrue(self.t.tick(at("09:50")).startswith("no new trades"))
        self.assertEqual(self.fake.orders, [])

    def test_market_holiday(self):
        self.fake.open_today = False
        live.arm(self.dir, DAY)
        self.assertEqual(self.t.tick(at("09:50")), "market closed today")

    def test_restart_does_not_rebuy(self):
        live.arm(self.dir, DAY)
        self.t.tick(at("09:50"))
        t2 = live.Trader(self.c, self.fake, self.dir, log=lambda *a: None, settle_seconds=0)
        t2.tick(at("09:50"))
        self.assertEqual(len(self.fake.orders), 1)


class TestPaperGuard(unittest.TestCase):
    def test_paper_by_default_and_live_needs_phrase(self):
        self.assertEqual(alpaca.trading_url(cfg()), alpaca.PAPER_URL)
        old = os.environ.pop("ALPACA_LIVE_CONFIRM", None)
        try:
            with self.assertRaises(alpaca.AlpacaError):
                alpaca.trading_url(cfg(paper=False))
            os.environ["ALPACA_LIVE_CONFIRM"] = alpaca.LIVE_PHRASE
            self.assertEqual(alpaca.trading_url(cfg(paper=False)), alpaca.LIVE_URL)
        finally:
            os.environ.pop("ALPACA_LIVE_CONFIRM", None)
            if old is not None:
                os.environ["ALPACA_LIVE_CONFIRM"] = old


if __name__ == "__main__":
    unittest.main()
