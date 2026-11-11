"""The strategy, as pure functions shared by the backtest and the live bot.

Long-only opening-range breakout, the same rule as day-trader-skill's
trader-entry and trader-exit:
  * opening range = high and low of the first `or_minutes` (9:30 to 9:45);
  * signal = the first completed bar, inside the entry window, that CLOSES
    above the range high (a wick above does not count);
  * entry = market order right after that bar closes (the backtest fills at
    the next bar's open, plus slippage);
  * stop = range midpoint, target = entry + target_r x risk;
  * anything still open is sold at `flat_by`.
"""
import math
from collections import namedtuple

from .bars import minute_of_day
from .config import hhmm

Signal = namedtuple("Signal", "symbol bar_index bar or_high or_low stop")
Plan = namedtuple("Plan", "symbol qty entry stop target risk_per_share")


def opening_range(day_bars, cfg):
    """(high, low) of the opening range, or None if it is incomplete."""
    end = 570 + cfg["or_minutes"]
    first = [b for b in day_bars if 570 <= minute_of_day(b.t) < end]
    if len(first) < cfg["or_minutes"] // cfg["bar_minutes"] or minute_of_day(first[0].t) != 570:
        return None
    return max(b.h for b in first), min(b.l for b in first)


def find_signal(symbol, day_bars, cfg, closed_through=None):
    """The first breakout bar, or None.

    closed_through: index of the last bar known to be complete (live use).
    """
    rng = opening_range(day_bars, cfg)
    if rng is None:
        return None
    hi, lo = rng
    stop = round((hi + lo) / 2, 2) if cfg["stop_rule"] == "or_mid" else round(lo, 2)
    earliest, latest = hhmm(cfg["no_entries_before"]), hhmm(cfg["no_entries_after"])
    last = len(day_bars) - 1 if closed_through is None else closed_through
    for i, b in enumerate(day_bars[: last + 1]):
        close_time = minute_of_day(b.t) + cfg["bar_minutes"]
        if minute_of_day(b.t) < 570 + cfg["or_minutes"] or close_time < earliest:
            continue
        if close_time > latest:
            return None
        if b.c > hi:
            if b.c < cfg["min_price"]:
                return None
            return Signal(symbol, i, b, hi, lo, stop)
    return None


def size(entry, stop, cfg, cash_available):
    """Whole shares bound by the max loss per trade, the position cap and cash."""
    per_share = entry - stop
    if per_share <= 0:
        return 0
    qty = math.floor(cfg["max_loss_per_trade_usd"] / per_share)
    qty = min(qty, math.floor(cfg["max_position_usd"] / entry), math.floor(cash_available / entry))
    return max(qty, 0)


def make_plan(signal, entry, cfg, cash_available):
    """Plan a trade at `entry`. None if the stop is not below the entry or size is 0."""
    risk = round(entry - signal.stop, 4)
    if risk <= 0:
        return None
    qty = size(entry, signal.stop, cfg, cash_available)
    if qty < 1:
        return None
    target = round(entry + cfg["target_r"] * risk, 2)
    return Plan(signal.symbol, qty, entry, signal.stop, target, risk)


def simulate_exit(day_bars, start_index, plan, cfg):
    """Walk bars from start_index (the entry bar) to the exit.

    Conservative fills: a stop gap fills at the bar's open, and a bar that
    touches both the stop and the target counts as the stop.
    Returns (exit_price_before_slippage, reason, exit_bar).
    """
    flat = hhmm(cfg["flat_by"])
    for b in day_bars[start_index:]:
        if minute_of_day(b.t) >= flat:
            return b.o, "flat", b
        if b.l <= plan.stop:
            return min(plan.stop, b.o), "stop", b
        if b.h >= plan.target:
            return max(plan.target, b.o), "target", b
    last = day_bars[-1]
    return last.c, "flat", last
