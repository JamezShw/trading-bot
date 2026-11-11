"""The live bot. It trades only on a day you have armed it.

  python -m bot arm     # you, each morning: confirm and switch it on for today
  python -m bot run     # leave running; waits until armed, trades, flattens by flat_by
  python -m bot stop    # kill switch: cancel the bot's orders, sell its positions, disarm

The arm only lasts for the New York date it was given on. After flat_by the
bot sells what it holds, disarms itself and stops until you arm it again.
"""
import datetime as dt
import json
import os
import time

from . import strategy
from .bars import NY, minute_of_day, parse_alpaca, regular_session
from .config import ROOT, hhmm
from .risk import DayRisk

STATE = os.path.join(ROOT, "state")


def _path(state_dir, name):
    os.makedirs(state_dir, exist_ok=True)
    return os.path.join(state_dir, name)


def _write(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2, default=str)
    os.replace(tmp, path)


def _read(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def armed_for(state_dir, day):
    a = _read(_path(state_dir, "armed.json"))
    return bool(a) and a.get("date") == day.isoformat()


def arm(state_dir, day, note=""):
    _write(_path(state_dir, "armed.json"), {"date": day.isoformat(),
                                            "armed_at": dt.datetime.now(NY).isoformat(), "note": note})
    try:
        os.remove(_path(state_dir, "stop"))
    except OSError:
        pass


def disarm(state_dir):
    try:
        os.remove(_path(state_dir, "armed.json"))
    except OSError:
        pass


def request_stop(state_dir):
    with open(_path(state_dir, "stop"), "w") as f:
        f.write(dt.datetime.now(NY).isoformat())
    disarm(state_dir)


def stop_requested(state_dir):
    return os.path.exists(_path(state_dir, "stop"))


class Trader:
    def __init__(self, cfg, client, state_dir=STATE, log=print, settle_seconds=1.0):
        self.cfg, self.client, self.state_dir, self.log = cfg, client, state_dir, log
        self.settle_seconds = settle_seconds   # pause between canceling orders and selling
        self.day = None

    # ---- per-day state -------------------------------------------------
    def _start_day(self, day):
        self.day = day
        self.risk = DayRisk(self.cfg)
        self.close_minute = 960
        cal = self.client.calendar(day.isoformat(), day.isoformat()) or []
        self.market_open_today = bool(cal) and cal[0].get("date") == day.isoformat()
        if self.market_open_today:
            h, m = cal[0]["close"].split(":")[:2]
            self.close_minute = int(h) * 60 + int(m)
        self.flat_minute = min(hhmm(self.cfg["flat_by"]), self.close_minute - 5)
        self.entry_cutoff = min(hhmm(self.cfg["no_entries_after"]), self.close_minute - 30)
        saved = _read(self._day_file(), {}) or {}
        self.traded = set(saved.get("traded", []))   # symbols the bot bought today
        self.orders = saved.get("orders", [])
        self.done = saved.get("done", False)
        for _ in self.traded:
            self.risk.trades += 1

    def _day_file(self):
        return _path(self.state_dir, "day-%s.json" % self.day.isoformat())

    def _save(self):
        _write(self._day_file(), {"traded": sorted(self.traded), "orders": self.orders, "done": self.done})

    # ---- the loop body ---------------------------------------------------
    def tick(self, now):
        """One pass. Returns a short status string."""
        day = now.astimezone(NY).date()
        if self.day != day:
            self._start_day(day)
        m = minute_of_day(now.astimezone(NY))

        if stop_requested(self.state_dir):
            if self.traded and not self.done:
                self.flatten("kill switch")
            return "stopped"
        if self.done:
            return "done for today"
        if not self.market_open_today:
            return "market closed today"
        if not armed_for(self.state_dir, day):
            return "waiting for you to arm today"
        if m >= self.flat_minute:
            self.flatten("flat by %02d:%02d" % divmod(self.flat_minute, 60))
            return "done for today"

        self._sync_pnl()
        if m < hhmm(self.cfg["no_entries_before"]) or m >= self.entry_cutoff:
            return "outside the entry window"
        if self.risk.halted:
            return "no new trades: " + self.risk.halted
        self._look_for_entries(now)
        return "watching"

    def _sync_pnl(self):
        acct = self.client.account()
        positions = {p["symbol"]: p for p in (self.client.positions() or [])}
        day_pnl = float(acct["equity"]) - float(acct["last_equity"])
        unreal = sum(float(p.get("unrealized_pl") or 0) for s, p in positions.items() if s in self.traded)
        self.risk.realized = day_pnl - unreal
        for s in list(self.risk.open_risk):
            if s not in positions:
                self.risk.open_risk.pop(s)
        if day_pnl <= -self.cfg["max_daily_loss_usd"]:
            self.risk.halt("daily loss limit hit (%.2f)" % day_pnl)
        self.positions = positions
        self.account = acct

    def _committed(self):
        return sum(abs(float(p.get("cost_basis") or 0)) for s, p in self.positions.items() if s in self.traded)

    def _look_for_entries(self, now):
        todo = [s for s in self.cfg["watchlist"] if s not in self.traded and s not in self.positions]
        if not todo:
            return
        start = now.astimezone(NY).replace(hour=9, minute=30, second=0, microsecond=0)
        raw = self.client.bars(todo, start.isoformat(), now.isoformat(), self.cfg["data_feed"])
        usable = self.cfg["budget"] * (1 - self.cfg["cash_buffer_pct"] / 100) - self._committed()
        cash = min(usable, float(self.account.get("cash", 0)))
        step = dt.timedelta(minutes=self.cfg["bar_minutes"])
        for sym in todo:
            bars = regular_session([parse_alpaca(r) for r in raw.get(sym, [])])
            closed = [i for i, b in enumerate(bars) if b.t + step <= now]
            if not closed:
                continue
            last = closed[-1]
            sig = strategy.find_signal(sym, bars, self.cfg, closed_through=last)
            # act only on a breakout that just happened; an older one was missed, like the backtest skips it
            if sig is None or sig.bar_index != last:
                continue
            plan = strategy.make_plan(sig, sig.bar.c, self.cfg, cash)
            if plan is None:
                continue
            risk = plan.qty * plan.risk_per_share
            ok, why = self.risk.allows(risk)
            if not ok:
                self.log("skip %s: %s" % (sym, why))
                continue
            coid = "orb-%s-%s" % (self.day.strftime("%Y%m%d"), sym)
            try:
                order = self.client.bracket_buy(sym, plan.qty, plan.stop, plan.target, coid)
            except Exception as e:   # one bad order must not stop the day
                self.log("order for %s failed: %s" % (sym, e))
                self.traded.add(sym)  # do not retry the same signal
                self._save()
                continue
            self.log("BUY %d %s ~%.2f stop %.2f target %.2f (risk $%.2f)%s" %
                     (plan.qty, sym, plan.entry, plan.stop, plan.target, risk,
                      "" if self.client.paper else "  [LIVE]"))
            self.traded.add(sym)
            self.risk.opened(sym, risk)
            cash -= plan.qty * plan.entry
            self.orders.append({"symbol": sym, "qty": plan.qty, "stop": plan.stop, "target": plan.target,
                                "signal_close": plan.entry, "id": (order or {}).get("id"),
                                "at": now.isoformat()})
            self._save()

    def flatten(self, why):
        """Cancel the bot's open orders and sell its positions. Leaves anything else alone."""
        self.log("flattening: %s" % why)
        mine = sorted(self.traded)
        if mine:
            for o in self.client.open_orders(mine) or []:
                try:
                    self.client.cancel_order(o["id"])
                except Exception as e:
                    self.log("cancel %s failed: %s" % (o.get("id"), e))
            time.sleep(self.settle_seconds)
            held = {p["symbol"] for p in (self.client.positions() or [])}
            for s in mine:
                if s in held:
                    try:
                        self.client.close_position(s)
                        self.log("sold %s" % s)
                    except Exception as e:
                        self.log("close %s failed: %s" % (s, e))
        self.done = True
        self._save()
        disarm(self.state_dir)


def seconds_to_next_bar(now, bar_minutes, lag=15):
    """Sleep until just after the next bar closes (data needs a few seconds)."""
    m = now.minute % bar_minutes
    nxt = now.replace(second=0, microsecond=0) + dt.timedelta(minutes=bar_minutes - m)
    return max(5, (nxt - now).total_seconds() + lag)


def run_forever(cfg, client, state_dir=STATE, log=print):
    t = Trader(cfg, client, state_dir, log)
    last = None
    while True:
        now = dt.datetime.now(NY)
        try:
            status = t.tick(now)
        except Exception as e:
            status = "error: %s" % e
        if status != last:
            log("%s  %s" % (now.strftime("%Y-%m-%d %H:%M:%S"), status))
            last = status
        if status in ("watching", "outside the entry window"):
            time.sleep(seconds_to_next_bar(now, cfg["bar_minutes"]))
        else:
            time.sleep(30)
