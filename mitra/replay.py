"""Replay: run the Analyst's scoring + the Trader's rules + the risk rules over the last N trading days.

Lets a beginner (or a judge) see a whole week of agent trading in seconds, using real past prices.
Replay uses price data only (no news, no AI calls), so it is fast and free to run any time.
"""
import pandas as pd

from mitra import lessons, market, portfolio, store, trader


def cut(df: pd.DataFrame, day) -> pd.DataFrame:
    return df[df.index.normalize() <= day]


def replay(market_code: str, tickers: list[str], risk: str = "medium", days: int = 7,
           capital: float | None = None) -> dict:
    cfg = market.MARKETS[market_code]
    capital = capital or portfolio.DEFAULT_CAPITAL[market_code]
    data = {}
    for t in tickers:
        try:
            data[t] = market.history(t)
        except Exception:
            continue
    if not data:
        raise RuntimeError("Could not load prices for any of the selected assets.")
    bench = market.history(cfg["benchmark"])
    # strip timezones so days from different exchanges line up
    data = {t: df.tz_localize(None) if df.index.tz is not None else df for t, df in data.items()}
    bench = bench.tz_localize(None) if bench.index.tz is not None else bench

    all_days = sorted(bench.index.normalize().unique())
    if len(all_days) < days + 60:
        days = max(1, min(days, len(all_days) - 60))
    play_days = all_days[-days:]
    start_day = all_days[-days - 1]

    p = portfolio.new(market_code, capital)
    p["start_benchmark"] = float(cut(bench, start_day)["Close"].iloc[-1])
    timeline = []
    sold_on: dict[str, int] = {}   # ticker -> index of the day it was sold (for the cool-off rule)
    for i, day in enumerate(play_days):
        assets = []
        for t, df in data.items():
            past = cut(df, day)
            if len(past) < 60:
                continue
            r = market.technicals(t, past)
            r.update(news_sentiment=0.0, news_reason="Replay uses price data only.", event="",
                     score=r["tech_score"])
            r["view"] = "Bullish" if r["score"] >= 25 else "Bearish" if r["score"] <= -25 else "Neutral"
            assets.append(r)
        if not assets:
            continue
        assets.sort(key=lambda r: -r["score"])
        insights = {"market": market_code, "market_name": cfg["name"], "currency": cfg["currency"], "assets": assets}
        prices = {r["ticker"]: r["price"] for r in assets}

        exits = trader.auto_exits(p, prices)
        done = trader.execute(p, exits, f"replay-{day.date()}")
        sold_on.update({t["ticker"]: i for t in done if t["side"] == "SELL"})
        cooling = {t for t, j in sold_on.items() if i - j < trader.COOL_OFF_DAYS}
        plan = trader.rule_based(insights, p)
        checked = trader.risk_check(plan, insights, p, risk, cooling)
        done += trader.execute(p, checked, f"replay-{day.date()}")
        sold_on.update({t["ticker"]: i for t in done if t["side"] == "SELL"})
        notable = [d for d in exits + checked if d["action"] != "HOLD" or d["status"] == "vetoed"]
        for d in notable:
            d["lesson"] = lessons.for_decision(d)

        bench_price = float(cut(bench, day)["Close"].iloc[-1])
        eq = portfolio.equity(p, prices)
        timeline.append({
            "date": str(day.date()), "equity": eq, "benchmark_price": bench_price,
            "return_pct": round((eq / capital - 1) * 100, 2),
            "benchmark_return_pct": round((bench_price / p["start_benchmark"] - 1) * 100, 2),
            "trades": done,
            "decisions": [{k: d.get(k) for k in ("ticker", "action", "status", "qty", "price", "stop_loss",
                                                  "target", "reason", "veto", "lesson")} for d in notable],
            "top_idea": {"ticker": assets[0]["ticker"], "score": assets[0]["score"],
                         "notes": assets[0]["tech_notes"]},
        })

    last_prices = {t: float(df["Close"].iloc[-1]) for t, df in data.items()}
    sc = portfolio.scorecard(p, last_prices, timeline[-1]["benchmark_price"] if timeline else None)
    return {"market": market_code, "market_name": cfg["name"], "currency": cfg["currency"],
            "benchmark_name": cfg["benchmark_name"], "risk": risk, "capital": capital,
            "days": timeline, "scorecard": sc, "created": store.now()}
