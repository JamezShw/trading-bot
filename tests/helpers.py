import datetime as dt

from bot.bars import NY, Bar
from bot.config import DEFAULTS


def cfg(**kw):
    c = dict(DEFAULTS)
    c.update(kw)
    return c


def day(prices, date=dt.date(2025, 3, 3), start="09:30"):
    """Bars from a list of (o, h, l, c) tuples, 5 minutes apart."""
    h, m = map(int, start.split(":"))
    t0 = dt.datetime(date.year, date.month, date.day, h, m, tzinfo=NY)
    return [Bar(t0 + dt.timedelta(minutes=5 * i), *p, 1000) for i, p in enumerate(prices)]


def flat_day(n=78, px=100.0, date=dt.date(2025, 3, 3)):
    return day([(px, px + 0.1, px - 0.1, px)] * n, date)


def breakout_day(date=dt.date(2025, 3, 3), after=None):
    """Range 99-101 (mid 100). Bar 3 (9:45) closes at 101.5, a breakout."""
    p = [(100, 101, 99, 100), (100, 100.5, 99.5, 100), (100, 100.8, 99.2, 100.5),
         (100.5, 101.6, 100.4, 101.5)]
    p += after if after is not None else [(101.5, 101.7, 101.3, 101.6)] * 74
    return day(p, date)
