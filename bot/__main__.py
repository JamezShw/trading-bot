"""Command line: python -m bot <command>."""
import argparse
import datetime as dt
import json
import os
import sys

from . import backtest, live
from .alpaca import Alpaca, AlpacaError
from .bars import NY
from .config import ROOT, load


def cmd_backtest(a, cfg):
    if a.symbols:
        cfg["watchlist"] = [s.strip().upper() for s in a.symbols.split(",")]
    client = None
    if not a.csv_dir:
        try:
            client = Alpaca(cfg)
        except AlpacaError as e:
            print("note: %s (only cached data can be used)" % e)
    bars = backtest.load_bars(cfg["watchlist"], a.start, a.end, cfg, client, a.csv_dir)
    trades = backtest.run(bars, cfg)
    s = backtest.summarize(trades, cfg)
    backtest.print_summary(s, cfg)
    out = os.path.join(ROOT, "reports", "backtest-%s-%s.csv" % (a.start, a.end))
    backtest.write_trades(out, trades)
    with open(out.replace(".csv", ".json"), "w") as f:
        json.dump(s, f, indent=2)
    print("trades written to %s" % os.path.relpath(out))


def cmd_arm(a, cfg):
    client = Alpaca(cfg)
    acct = client.account()
    today = dt.datetime.now(NY).date()
    cal = client.calendar(today.isoformat(), today.isoformat()) or []
    if not cal or cal[0].get("date") != today.isoformat():
        sys.exit("The market is closed today (%s). Nothing armed." % today)
    print("Account:  %s, equity $%s, cash $%s" % ("PAPER" if client.paper else "LIVE (real money)",
                                                  acct["equity"], acct["cash"]))
    print("Today:    %s, market %s to %s New York time" % (today, cal[0]["open"], cal[0]["close"]))
    print("Limits:   $%d budget, $%d max loss per trade, $%d per day, %d trades per day" % (
        cfg["budget"], cfg["max_loss_per_trade_usd"], cfg["max_daily_loss_usd"], cfg["max_trades_per_day"]))
    print("Watching: %s" % ", ".join(cfg["watchlist"]))
    print("It trades on its own from %s to %s and sells everything by %s." % (
        cfg["no_entries_before"], cfg["no_entries_after"], cfg["flat_by"]))
    if not a.yes:
        if input('Type "start" to arm it for today: ').strip().lower() != "start":
            sys.exit("Not armed.")
    live.arm(live.STATE, today, "paper" if client.paper else "LIVE")
    print("Armed for %s. Kill switch: python -m bot stop" % today)


def cmd_stop(a, cfg):
    live.request_stop(live.STATE)
    print("Stop requested and disarmed.")
    try:
        t = live.Trader(cfg, Alpaca(cfg))
        t._start_day(dt.datetime.now(NY).date())
        if t.traded:
            t.flatten("kill switch")
    except AlpacaError as e:
        print("Could not reach Alpaca to sell (%s). The running bot will sell on its next check." % e)


def cmd_disarm(a, cfg):
    live.disarm(live.STATE)
    print("Disarmed. Open positions keep their stop and target; run `python -m bot stop` to sell them now.")


def cmd_status(a, cfg):
    today = dt.datetime.now(NY).date()
    print("armed for today: %s" % ("yes" if live.armed_for(live.STATE, today) else "no"))
    day = os.path.join(live.STATE, "day-%s.json" % today)
    if os.path.exists(day):
        print(open(day).read())


def cmd_run(a, cfg):
    client = Alpaca(cfg)
    print("Bot running on the %s account. Waiting for `python -m bot arm` each day." %
          ("PAPER" if client.paper else "LIVE"))
    live.run_forever(cfg, client)


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m bot", description=__doc__)
    p.add_argument("--config", help="path to config.json")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backtest", help="test the strategy on past data")
    b.add_argument("--start", default="2022-01-01")
    b.add_argument("--end", default=(dt.date.today() - dt.timedelta(days=1)).isoformat())
    b.add_argument("--symbols", help="comma separated; default: the watchlist")
    b.add_argument("--csv-dir", help="read <SYMBOL>.csv bars from here instead of Alpaca")
    ar = sub.add_parser("arm", help="switch the bot on for today")
    ar.add_argument("--yes", action="store_true", help="skip the typed confirmation")
    sub.add_parser("disarm", help="no new trades today")
    sub.add_parser("stop", help="kill switch: cancel orders, sell positions, disarm")
    sub.add_parser("status", help="armed or not, and today's orders")
    sub.add_parser("run", help="the bot loop")
    a = p.parse_args(argv)
    cfg = load(a.config)
    {"backtest": cmd_backtest, "arm": cmd_arm, "disarm": cmd_disarm, "stop": cmd_stop,
     "status": cmd_status, "run": cmd_run}[a.cmd](a, cfg)


if __name__ == "__main__":
    main()
