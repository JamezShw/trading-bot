"""A small Alpaca REST client (standard library only).

Keys come from the ALPACA_API_KEY and ALPACA_SECRET_KEY environment
variables, never from files in this repo. The paper endpoint is used unless
config "paper" is false AND the environment variable ALPACA_LIVE_CONFIRM is
set to "I accept the risk"; both have to be changed by hand.
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

PAPER_URL = "https://paper-api.alpaca.markets"
LIVE_URL = "https://api.alpaca.markets"
DATA_URL = "https://data.alpaca.markets"
LIVE_PHRASE = "I accept the risk"


class AlpacaError(Exception):
    pass


def keys():
    k, s = os.environ.get("ALPACA_API_KEY"), os.environ.get("ALPACA_SECRET_KEY")
    if not k or not s:
        raise AlpacaError("set ALPACA_API_KEY and ALPACA_SECRET_KEY (paper keys) in the environment")
    return k, s


def trading_url(cfg):
    if cfg.get("paper", True):
        return PAPER_URL
    if os.environ.get("ALPACA_LIVE_CONFIRM") != LIVE_PHRASE:
        raise AlpacaError('config says live trading, but ALPACA_LIVE_CONFIRM is not "%s"; refusing' % LIVE_PHRASE)
    return LIVE_URL


class Alpaca:
    def __init__(self, cfg, key=None, secret=None):
        self.cfg = cfg
        self.key, self.secret = (key, secret) if key else keys()
        self.base = trading_url(cfg)
        self.paper = self.base == PAPER_URL

    def _req(self, method, url, params=None, body=None, retries=3):
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode() if body is not None else None
        headers = {"APCA-API-KEY-ID": self.key, "APCA-API-SECRET-KEY": self.secret,
                   "Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        for attempt in range(retries):
            req = urllib.request.Request(url, data=data, method=method, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    raw = r.read()
                    return json.loads(raw) if raw else None
            except urllib.error.HTTPError as e:
                msg = e.read().decode("utf-8", "replace")[:500]
                # retry rate limits and server errors on reads only; never resend an order
                if (e.code == 429 or e.code >= 500) and method == "GET" and attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise AlpacaError("%s %s -> HTTP %d: %s" % (method, url.split("?")[0], e.code, msg))
            except urllib.error.URLError as e:
                if method == "GET" and attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise AlpacaError("%s %s failed: %s" % (method, url.split("?")[0], e.reason))

    # trading
    def account(self):
        return self._req("GET", self.base + "/v2/account")

    def clock(self):
        return self._req("GET", self.base + "/v2/clock")

    def calendar(self, start, end):
        return self._req("GET", self.base + "/v2/calendar", {"start": start, "end": end})

    def positions(self):
        return self._req("GET", self.base + "/v2/positions")

    def open_orders(self, symbols=None):
        p = {"status": "open", "nested": "true", "limit": 500}
        if symbols:
            p["symbols"] = ",".join(symbols)
        return self._req("GET", self.base + "/v2/orders", p)

    def bracket_buy(self, symbol, qty, stop, target, client_order_id):
        body = {"symbol": symbol, "qty": str(int(qty)), "side": "buy", "type": "market",
                "time_in_force": "day", "order_class": "bracket",
                "take_profit": {"limit_price": "%.2f" % target},
                "stop_loss": {"stop_price": "%.2f" % stop},
                "client_order_id": client_order_id}
        return self._req("POST", self.base + "/v2/orders", body=body)

    def cancel_order(self, order_id):
        return self._req("DELETE", self.base + "/v2/orders/" + order_id)

    def close_position(self, symbol):
        return self._req("DELETE", self.base + "/v2/positions/" + urllib.parse.quote(symbol))

    # market data
    def bars(self, symbols, start, end, feed, timeframe="5Min"):
        """{symbol: [raw bar dicts]} between ISO times start and end."""
        out = {s: [] for s in symbols}
        params = {"symbols": ",".join(symbols), "timeframe": timeframe, "start": start, "end": end,
                  "limit": 10000, "adjustment": "split", "feed": feed, "sort": "asc"}
        while True:
            res = self._req("GET", DATA_URL + "/v2/stocks/bars", params)
            for sym, rows in (res.get("bars") or {}).items():
                out.setdefault(sym, []).extend(rows)
            token = res.get("next_page_token")
            if not token:
                return out
            params["page_token"] = token
