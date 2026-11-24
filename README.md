# Market Mitra

**An Analyst agent finds the opportunities. A Trader agent acts on them. Every trade explained.**

Two AI agents work together in a **BAND** room to analyse Indian stocks (NSE), US stocks and crypto,
then make **simulated (paper) trades** with hard risk rules, and track the results against the index.

Built for *Diwali Festiverse: The Agent-to-Agent Hackathon (India Edition)*, **Finance — Analyze & Trade** track.

> Paper trading only. No real money, no broker connection. For learning, not investment advice.

## The problem
New investors in India see tips everywhere but can't tell *why* a stock might move, how much to risk,
or when to get out. Most apps either show raw charts or give one-line "buy" calls with no reasoning
and no risk control.

## How it works

```
User picks a market (NSE / US / Crypto), assets and a risk level
        │
        ▼
Mitra Desk (web app) ──@Market Analyst analyse market=IN req=…──▶ Market Analyst
                                                                    │ 6 months of prices (Yahoo Finance)
                                                                    │ RSI, 20/50-day averages, momentum, ATR, volume
                                                                    │ live news sentiment (Gemini + Google Search)
                                                                    ▼ ranks the opportunities
                                              INSIGHTS_READY ──▶ Market Trader
                                                                    │ decides BUY / SELL / HOLD with stop-loss + target
            Market Analyst ◀──── NEED_MORE tickers=X,Y ─────────────┤ (if unsure about some assets)
            bull case, bear case, key risk ── INSIGHTS_READY round=2 ▶│
                                                                    │ Risk rules approve or VETO each trade
                                                                    ▼ simulated fills, portfolio updated
Mitra Desk ◀── TRADES_DONE ── user sees the agents' conversation, every decision with its reason,
                              the portfolio and how it compares with Nifty 50 / S&P 500 / Bitcoin
```

| Agent | Job |
|---|---|
| **Market Analyst** | Gathers market data, tracks trends, reads the news, scores and ranks opportunities. Does a deeper "second look" when the Trader asks |
| **Market Trader** | Uses the Analyst's insights to decide trades, asks the Analyst when unsure, explains every decision in plain words |
| **Risk rules** | Hard limits no AI decision can override: max size per trade, max open positions, minimum confidence, overbought filter, mandatory stop-loss |
| **Mitra Desk** | The web app: starts runs, shows the live agent conversation, trades and scorecard |

Risk levels:

| | Low | Medium | High |
|---|---|---|---|
| Max per trade | 10% | 20% | 30% |
| Max open positions | 4 | 5 | 6 |
| Min confidence | 65% | 55% | 45% |
| Max stop-loss distance | 5% | 8% | 12% |
| Cool-off after selling | 3 days | 3 days | 3 days |
| Skip if RSI above | 72 | 78 | 85 |

Open positions are closed automatically when their stop-loss or target is hit.

## Two ways to use it
- **Live run**: the Analyst and Trader talk on BAND with today's prices and news (about 2 minutes). Trades go into a paper portfolio
  (₹50,000 for NSE, $10,000 for US stocks and crypto) that keeps running between sessions.
- **⏪ Replay last 7 days**: the same scoring, trader rules and risk rules played day by day over the last 7 trading days with
  real past prices. A beginner sees a whole week of decisions, lessons and profit/loss vs the index in seconds.

## What makes it different
- **Two agents that really disagree and check each other**: the Trader asks the Analyst for a second look before risking money; the risk rules can veto the Trader.
- **Every trade is explained** in plain language, with the news and numbers behind it.
- **A 📘 lesson with every decision**: stop-loss, position sizing, RSI, trend, revenge trading, booking profit...
  The beginner learns the concept at the moment it matters.
- **Behaves like a disciplined trader**: a 3-day cool-off after selling (no revenge trading), automatic exits at stop-loss or target.
- **Scorecard vs the index**: is the strategy beating just holding Nifty 50 / S&P 500 / Bitcoin?
- **All three markets** in one place: NSE stocks (₹), US stocks ($) and crypto (fractional units).
- **Keeps working** if the AI is busy: model fallback, and simple rule-based scoring/trading as a backup.

## Tech
- **BAND**: agent-to-agent messaging (`band-sdk`, LangGraph adapter; REST API for the web app)
- **Gemini API** (`gemini-3.5-flash` with automatic fallback): news sentiment with Google Search grounding, trade decisions, deep dives
- **Yahoo Finance** (`yfinance`): daily prices for NSE, US stocks, crypto and the benchmarks
- **FastAPI**: the Mitra Desk web app (`web/`)
- **GitHub Codespaces**: runs the agents and the web app

## Run it

1. Open this repo in **GitHub Codespaces**.
2. Add **Codespaces secrets**: `GEMINI_API_KEY`, `MITRA_ANALYST_ID`, `MITRA_ANALYST_KEY`, `MITRA_TRADER_ID`, `MITRA_TRADER_KEY`
   (BAND agents named "Market Analyst" and "Market Trader", in the same room).
3. `bash scripts/start_all.sh` - it prints the web app link.
4. Open the link, pick a market, and press **Run the agents**.

## Project layout
```
agents/analyst_agent.py   Market Analyst (BAND agent)
agents/trader_agent.py    Market Trader (BAND agent)
mitra/market.py           prices + indicators
mitra/analyst.py          news sentiment, scoring, deep dive
mitra/trader.py           decisions, risk rules, simulated execution
mitra/portfolio.py        paper portfolio + scorecard
mitra/replay.py           replay the last N trading days
mitra/lessons.py          beginner lessons attached to decisions
mitra/band_helper.py      BAND connection
web/                      Mitra Desk web app
```

## Disclaimer
Simulated trades for education only. Prices may be delayed. This is not investment advice.
