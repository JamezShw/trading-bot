"""5-minute bars, New York time, and CSV caching."""
import csv
import datetime as dt
from collections import namedtuple
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
UTC = dt.timezone.utc

# t is the bar's START time, timezone-aware, in New York time
Bar = namedtuple("Bar", "t o h l c v")


def minute_of_day(t):
    return t.hour * 60 + t.minute


def parse_alpaca(raw):
    """One bar from Alpaca's JSON: {"t": "2024-01-03T14:30:00Z", "o":.., ...}."""
    t = dt.datetime.fromisoformat(raw["t"].replace("Z", "+00:00")).astimezone(NY)
    return Bar(t, float(raw["o"]), float(raw["h"]), float(raw["l"]), float(raw["c"]), float(raw.get("v", 0)))


def regular_session(bars):
    """Keep 9:30 to 16:00 bars only."""
    return [b for b in bars if 570 <= minute_of_day(b.t) < 960]


def by_day(bars):
    days = {}
    for b in sorted(bars, key=lambda b: b.t):
        days.setdefault(b.t.date(), []).append(b)
    return days


def write_csv(path, bars):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "open", "high", "low", "close", "volume"])
        for b in bars:
            w.writerow([b.t.isoformat(), b.o, b.h, b.l, b.c, b.v])


def read_csv(path):
    out = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            t = dt.datetime.fromisoformat(row["time"])
            if t.tzinfo is None:
                t = t.replace(tzinfo=NY)
            out.append(Bar(t.astimezone(NY), float(row["open"]), float(row["high"]),
                           float(row["low"]), float(row["close"]), float(row.get("volume") or 0)))
    return out
