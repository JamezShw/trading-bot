"""Settings. Defaults mirror the limits in day-trader-skill's config.example.json.

Override any of them in config.json at the repo root (see config.example.json).
"""
import json
import os

DEFAULTS = {
    # account and risk limits
    "budget": 5000,                 # dollars the bot may use
    "cash_buffer_pct": 10,          # keep this % of the budget unused
    "max_position_usd": 4000,       # cap on one position's cost
    "max_loss_per_trade_usd": 50,   # loss at the stop, sizes every trade
    "max_daily_loss_usd": 150,      # stop opening trades once losses + open risk would pass this
    "max_trades_per_day": 3,
    # strategy: long-only 15-minute opening-range breakout on 5-minute bars
    "watchlist": ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "AMD", "TSLA", "META", "AMZN", "GOOGL"],
    "or_minutes": 15,
    "bar_minutes": 5,
    "target_r": 1.0,                # target = entry + target_r x (entry - stop)
    "stop_rule": "or_mid",          # or_mid (range midpoint) or or_low (range low)
    "min_price": 5.0,
    "no_entries_before": "09:45",   # New York time
    "no_entries_after": "15:30",
    "flat_by": "15:55",
    # costs used by the backtest
    "slippage_bps": 5,              # each side, on market and stop fills
    "commission_per_share": 0.0,    # Alpaca charges no commission
    "sell_fee_bps": 0.3,            # rough SEC + FINRA TAF fees on sells
    # broker
    "paper": True,
    "data_feed": "iex",             # live bars: iex is free; sip needs a paid plan
    "backtest_feed": "sip",         # historical SIP bars are free on Alpaca except the last 15 minutes
}

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(path=None):
    cfg = dict(DEFAULTS)
    path = path or os.path.join(ROOT, "config.json")
    if os.path.exists(path):
        with open(path) as f:
            user = json.load(f)
        unknown = set(user) - set(DEFAULTS)
        if unknown:
            raise ValueError("unknown settings in %s: %s" % (path, ", ".join(sorted(unknown))))
        cfg.update(user)
    cfg["watchlist"] = [s.upper() for s in cfg["watchlist"]]
    return cfg


def hhmm(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)
