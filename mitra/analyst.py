"""ANALYST work: prices + indicators + live news sentiment -> ranked opportunities."""
import logging

from mitra import gemini, market, store

NEWS_PROMPT = """You are a market analyst. Search the web for the most recent news (last 7 days) about each of
these {market_name} assets: {tickers}.
For each one give a news sentiment score from -1 (very negative) to +1 (very positive),
one short headline-style reason (max 20 words), and any big upcoming event (results, launch, policy) or "".
Also give one sentence on the overall market mood today.
Return JSON: {{"market_mood": "...", "assets": [{{"ticker": "SAME TICKER AS GIVEN", "sentiment": 0.3,
"reason": "...", "event": "..."}}]}}"""

DEEP_PROMPT = """You are a careful equity/crypto research analyst. The trader is unsure about: {tickers}
({market_name}). For each, search the latest news and give: the bull case (1 sentence), the bear case (1 sentence),
key risk in the next 2 weeks (1 sentence), and your conviction to BUY now from 0 to 1.
Technical context: {context}
Return JSON: {{"assets": [{{"ticker": "SAME TICKER AS GIVEN", "bull": "...", "bear": "...", "risk": "...",
"conviction": 0.5}}]}}"""


def insights_path(req_id: str):
    return store.WORK / "insights" / f"{req_id}.json"


def news(market_code: str, tickers: list[str]) -> tuple[dict, list[dict]]:
    cfg = market.MARKETS[market_code]
    try:
        data, sources = gemini.ask_web(NEWS_PROMPT.format(market_name=cfg["name"], tickers=", ".join(tickers)))
    except Exception as err:  # quota / network: keep going with technicals only
        logging.warning("news check failed: %s", err)
        return {}, []
    data = data if isinstance(data, dict) else {}
    return data, sources


def analyse(market_code: str, tickers: list[str], req_id: str) -> dict:
    cfg = market.MARKETS[market_code]
    rows, failed = [], []
    for t in tickers:
        try:
            rows.append(market.technicals(t))
        except Exception as err:
            logging.warning("price data failed for %s: %s", t, err)
            failed.append(t)
    if not rows:
        raise RuntimeError("Could not load prices for any of the selected assets.")

    news_data, sources = news(market_code, [r["ticker"] for r in rows])
    by_ticker = {str(a.get("ticker", "")).upper(): a for a in news_data.get("assets", []) if isinstance(a, dict)}
    for r in rows:
        n = by_ticker.get(r["ticker"].upper(), {})
        try:
            sentiment = max(-1.0, min(1.0, float(n.get("sentiment", 0) or 0)))
        except (TypeError, ValueError):
            sentiment = 0.0
        r["news_sentiment"] = round(sentiment, 2)
        r["news_reason"] = str(n.get("reason", "") or ("No major news found." if n else "News check unavailable right now."))
        r["event"] = str(n.get("event", "") or "")
        # combined score: 60% price action, 40% news (price action only if there is no news read)
        r["score"] = round(0.6 * r["tech_score"] + 0.4 * sentiment * 100) if n else r["tech_score"]
        r["view"] = "Bullish" if r["score"] >= 25 else "Bearish" if r["score"] <= -25 else "Neutral"
    rows.sort(key=lambda r: -r["score"])

    try:
        bench = market.technicals(cfg["benchmark"])
        benchmark = {"ticker": cfg["benchmark"], "name": cfg["benchmark_name"], "price": bench["price"],
                     "change_1d": bench["change_1d"], "change_20d": bench["change_20d"]}
    except Exception as err:
        logging.warning("benchmark failed: %s", err)
        benchmark = {"ticker": cfg["benchmark"], "name": cfg["benchmark_name"]}

    insights = {
        "req": req_id, "market": market_code, "market_name": cfg["name"], "currency": cfg["currency"],
        "created": store.now(), "assets": rows, "failed": failed, "benchmark": benchmark,
        "market_mood": str(news_data.get("market_mood", "") or ""), "sources": sources[:6], "deep_dive": {},
    }
    store.write_json(insights_path(req_id), insights)
    return insights


def deep_dive(req_id: str, tickers: list[str]) -> dict:
    """Second look at assets the Trader is unsure about (the Trader asks for this)."""
    insights = store.read_json(insights_path(req_id), None)
    if insights is None:
        raise RuntimeError("Insights not found for this run.")
    rows = {r["ticker"]: r for r in insights["assets"]}
    tickers = [t for t in tickers if t in rows]
    context = "; ".join(f"{t}: price {rows[t]['price']}, RSI {rows[t]['rsi']}, 20d {rows[t]['change_20d']}%, "
                        f"score {rows[t]['score']}" for t in tickers)
    try:
        data, sources = gemini.ask_web(DEEP_PROMPT.format(
            tickers=", ".join(tickers), market_name=insights["market_name"], context=context))
    except Exception as err:
        logging.warning("deep dive failed: %s", err)
        data, sources = {}, []
    found = {str(a.get("ticker", "")).upper(): a for a in (data or {}).get("assets", []) if isinstance(a, dict)} \
        if isinstance(data, dict) else {}
    for t in tickers:
        a = found.get(t.upper())
        if a:
            insights["deep_dive"][t] = {k: a.get(k) for k in ("bull", "bear", "risk", "conviction")}
        else:
            insights["deep_dive"][t] = {"bull": "", "bear": "", "risk": "No extra information found.", "conviction": 0.3}
    insights["sources"] = (insights.get("sources") or []) + sources[:4]
    store.write_json(insights_path(req_id), insights)
    return insights
