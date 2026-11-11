"""Daily limits, shared by the backtest and the live bot."""


class DayRisk:
    """Tracks one trading day: trades taken, realized P&L, open risk."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.trades = 0
        self.realized = 0.0      # dollars, after costs
        self.open_risk = {}      # symbol -> dollars at risk to the stop
        self.halted = None       # reason, once the day is halted

    def allows(self, new_risk):
        """(ok, reason) for a new trade with `new_risk` dollars to its stop."""
        c = self.cfg
        if self.halted:
            return False, self.halted
        if self.trades >= c["max_trades_per_day"]:
            return False, "max %d trades per day reached" % c["max_trades_per_day"]
        if new_risk > c["max_loss_per_trade_usd"] + 1e-9:
            return False, "risk %.2f over the %.2f max loss per trade" % (new_risk, c["max_loss_per_trade_usd"])
        worst = -min(self.realized, 0) + sum(self.open_risk.values()) + new_risk
        if worst > c["max_daily_loss_usd"] + 1e-9:
            return False, "could lose %.2f today, over the %.2f daily limit" % (worst, c["max_daily_loss_usd"])
        return True, "ok"

    def opened(self, symbol, risk):
        self.trades += 1
        self.open_risk[symbol] = risk

    def closed(self, symbol, pnl):
        self.open_risk.pop(symbol, None)
        self.realized += pnl
        if -self.realized >= self.cfg["max_daily_loss_usd"]:
            self.halted = "daily loss limit hit (%.2f)" % self.realized

    def halt(self, reason):
        self.halted = reason
