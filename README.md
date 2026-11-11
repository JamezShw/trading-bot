# trading-bot

An automated day-trading bot for Alpaca. It trades on the **paper** account
by default, and only on days you switch it on.

> Not financial advice. Most day-trading strategies lose money once fees and
> slippage are counted. Backtest it, then paper trade it for weeks before
> you think about real money.

## The strategy

The rules come from the opening-range breakout in
[day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill)
(MIT, by Jake Schincariol). This repo reimplements them and copies no code.

- **Opening range:** the high and low of 9:30 to 9:45 New York time.
- **Buy:** the first 5-minute bar that *closes* above the range high, between
  9:45 and 15:30. A wick above the high does not count. The bot only acts on
  a breakout that just happened. If it missed one, it does not chase it.
- **Order:** a bracket order. It buys at market, with a stop-loss at the
  range midpoint and a take-profit at 1× the risk.
- **Close out:** anything still open is sold at 15:55.
- **Long only.** No shorting, margin, or options.

## The limits (config.json)

| setting | default |
| --- | --- |
| budget the bot may use | $5,000 (10 % kept back) |
| max loss per trade, at the stop | $50 |
| max loss per day | $150, counting open risk; the bot stops for the day when it is hit |
| max trades per day | 3 |
| max cost of one position | $4,000 |
| watchlist | SPY, QQQ, AAPL, MSFT, NVDA, AMD, TSLA, META, AMZN, GOOGL |

To change any of these, copy `config.example.json` to `config.json` and
edit it.

## Setup

You need Python 3.9 or newer. No packages to install.

Create **paper** API keys in the Alpaca dashboard and put them in the
environment. Don't put them in a file in this repo.

```bash
export ALPACA_API_KEY=...
export ALPACA_SECRET_KEY=...
```

## Backtest first

```bash
python -m bot backtest --start 2021-01-01 --end 2025-12-31
```

The backtest downloads 5-minute bars from Alpaca and caches them in `data/`.
It runs the same rules and the same daily limits as the live bot, and it
fills orders conservatively:

- Entries fill at the next bar's open, plus slippage.
- Stops fill at the stop price or worse, and a gap fills at the bar's open.
- A bar that touches both the stop and the target counts as the stop.
- Slippage and sell fees are subtracted from every trade.

It prints win rate, average R, net and pre-cost P&L, profit factor, max
drawdown and a year-by-year breakdown. Every trade is written to `reports/`.

## Running it day to day

```bash
python -m bot run      # leave this running on a machine that stays on
python -m bot arm      # each morning: shows the account and limits, type "start"
python -m bot status   # armed? what did it buy?
python -m bot stop     # kill switch: cancel its orders, sell its positions, disarm
python -m bot disarm   # no new trades today (open trades keep their stop/target)
```

- **No arm, no trades.** An arm only counts for the New York date you gave
  it on.
- After 15:55 the bot sells what it bought, disarms itself and waits for the
  next day.
- It only cancels and sells the positions it opened itself. Anything else in
  the account is left alone.
- If it is restarted mid-day, it remembers what it already bought (in
  `state/`) and won't buy again.

### Real money

The bot uses Alpaca's paper endpoint unless **both** of these are true:

- `"paper": false` is set in `config.json`.
- The environment variable `ALPACA_LIVE_CONFIRM` is set to
  `I accept the risk`.

## Tests

```bash
python -m unittest discover -s tests -t . -v
```
