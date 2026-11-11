"""Backtest the strategy over years of 5-minute bars, with costs.

Every day runs the same rules and the same daily limits as the live bot:
signals from all watchlist symbols are taken in time order, each one only if
the daily limits and the cash allow it.
"""
import csv
import datetime as dt
import os
from collections import defaultdict

from . import strategy
from .bars import by_day, minute_of_day, parse_alpaca, read_csv, regular_session, write_csv
from .config import ROOT, hhmm
from .risk import DayRisk

CACHE = os.path.join(ROOT, "data", "cache")


def load_bars(symbols, start, end, cfg, client=None, csv_dir=None):
    """{symbol: [Bar]} from csv_dir/<SYMBOL>.csv, the cache, or Alpaca."""
    out = {}
    os.makedirs(CACHE, exist_ok=True)
    for sym in symbols:
        if csv_dir:
            path = os.path.join(csv_dir, sym + ".csv")
            out[sym] = read_csv(path) if os.path.exists(path) else []
            continue
        path = os.path.join(CACHE, "%s-5Min-%s-%s-%s.csv" % (sym, start, end, cfg["backtest_feed"]))
        if not os.path.exists(path):
            if client is None:
                raise SystemExit("no cached bars for %s; set ALPACA_API_KEY / ALPACA_SECRET_KEY" % sym)
            print("downloading %s %s..%s" % (sym, start, end), flush=True)
            raw = client.bars([sym], start + "T00:00:00Z", end + "T23:59:59Z", cfg["backtest_feed"])[sym]
            write_csv(path, [parse_alpaca(r) for r in raw])
        out[sym] = read_csv(path)
    return out


def costs(qty, entry_fill, exit_fill, cfg):
    return qty * cfg["commission_per_share"] * 2 + qty * exit_fill * cfg["sell_fee_bps"] / 1e4


def run(bars_by_symbol, cfg):
    """List of trade dicts, one per trade taken."""
    slip = cfg["slippage_bps"] / 1e4
    flat = hhmm(cfg["flat_by"])
    usable = cfg["budget"] * (1 - cfg["cash_buffer_pct"] / 100)
    days = defaultdict(dict)
    for sym, bars in bars_by_symbol.items():
        for d, day_bars in by_day(regular_session(bars)).items():
            days[d][sym] = day_bars

    trades = []
    for d in sorted(days):
        cands = []
        for sym, day_bars in days[d].items():
            sig = strategy.find_signal(sym, day_bars, cfg)
            if not sig or sig.bar_index + 1 >= len(day_bars):
                continue
            entry_bar = day_bars[sig.bar_index + 1]
            if minute_of_day(entry_bar.t) >= flat:
                continue
            cands.append((entry_bar.t, sym, sig, day_bars))
        cands.sort(key=lambda c: (c[0], c[1]))

        risk = DayRisk(cfg)
        open_trades = []   # (exit_time, trade, cost_basis)
        cash = usable
        for t, sym, sig, day_bars in cands:
            for ot in sorted(open_trades, key=lambda x: x[0]):
                if ot[0] <= t:
                    risk.closed(ot[1]["symbol"], ot[1]["pnl"])
                    cash += ot[2] + ot[1]["pnl"]
                    open_trades.remove(ot)
            i = sig.bar_index + 1
            entry_fill = round(day_bars[i].o * (1 + slip), 4)
            plan = strategy.make_plan(sig, entry_fill, cfg, cash)
            if plan is None:
                continue
            ok, _ = risk.allows(plan.qty * plan.risk_per_share)
            if not ok:
                continue
            px, reason, xbar = strategy.simulate_exit(day_bars, i, plan, cfg)
            exit_fill = px if reason == "target" else px * (1 - slip)
            gross = (px - day_bars[i].o) * plan.qty
            pnl = (exit_fill - entry_fill) * plan.qty - costs(plan.qty, entry_fill, exit_fill, cfg)
            trade = {"date": d.isoformat(), "symbol": sym, "signal_time": sig.bar.t.strftime("%H:%M"),
                     "entry_time": day_bars[i].t.strftime("%H:%M"), "qty": plan.qty,
                     "entry": round(entry_fill, 4), "stop": plan.stop, "target": plan.target,
                     "exit_time": xbar.t.strftime("%H:%M"), "exit": round(exit_fill, 4), "reason": reason,
                     "gross_pnl": round(gross, 2), "pnl": round(pnl, 2),
                     "r": round(pnl / (plan.qty * plan.risk_per_share), 3)}
            risk.opened(sym, plan.qty * plan.risk_per_share)
            cost_basis = plan.qty * entry_fill
            cash -= cost_basis
            # a stop or target exit happens during its bar; count the cash back after that bar
            open_trades.append((xbar.t + dt.timedelta(minutes=cfg["bar_minutes"]), trade, cost_basis))
            trades.append(trade)
    return trades


def summarize(trades, cfg):
    if not trades:
        return {"trades": 0}
    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    daily = defaultdict(float)
    for t in trades:
        daily[t["date"]] += t["pnl"]
    equity, peak, dd = 0.0, 0.0, 0.0
    for d in sorted(daily):
        equity += daily[d]
        peak = max(peak, equity)
        dd = min(dd, equity - peak)
    by_year = defaultdict(lambda: [0, 0.0])
    for t in trades:
        y = by_year[t["date"][:4]]
        y[0] += 1
        y[1] += t["pnl"]
    reasons = defaultdict(int)
    for t in trades:
        reasons[t["reason"]] += 1
    return {
        "trades": len(trades),
        "days_traded": len(daily),
        "win_rate": round(len(wins) / len(trades), 3),
        "avg_r": round(sum(t["r"] for t in trades) / len(trades), 3),
        "net_pnl": round(sum(pnls), 2),
        "gross_pnl": round(sum(t["gross_pnl"] for t in trades), 2),
        "profit_factor": round(sum(wins) / -sum(losses), 2) if losses and sum(losses) < 0 else None,
        "max_drawdown": round(dd, 2),
        "return_on_budget_pct": round(100 * sum(pnls) / cfg["budget"], 1),
        "exits": dict(reasons),
        "by_year": {y: {"trades": v[0], "pnl": round(v[1], 2)} for y, v in sorted(by_year.items())},
    }


def write_trades(path, trades):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        if not trades:
            return
        w = csv.DictWriter(f, fieldnames=list(trades[0]))
        w.writeheader()
        w.writerows(trades)


def print_summary(s, cfg):
    if not s["trades"]:
        print("No trades.")
        return
    print("Opening-range breakout, %d symbols, $%d budget, $%d max loss/trade" %
          (len(cfg["watchlist"]), cfg["budget"], cfg["max_loss_per_trade_usd"]))
    print("  trades           %d on %d days" % (s["trades"], s["days_traded"]))
    print("  win rate         %.1f%%" % (100 * s["win_rate"]))
    print("  average trade    %+.3f R" % s["avg_r"])
    print("  net P&L          $%+.2f  (%+.1f%% of budget; before costs $%+.2f)" %
          (s["net_pnl"], s["return_on_budget_pct"], s["gross_pnl"]))
    print("  profit factor    %s" % s["profit_factor"])
    print("  max drawdown     $%.2f" % s["max_drawdown"])
    print("  exits            %s" % ", ".join("%s %d" % kv for kv in sorted(s["exits"].items())))
    for y, v in s["by_year"].items():
        print("  %s             %4d trades  $%+.2f" % (y, v["trades"], v["pnl"]))
