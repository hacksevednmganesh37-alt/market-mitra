"""ANALYST work: prices + indicators + live news sentiment -> ranked opportunities."""
import logging
from concurrent.futures import ThreadPoolExecutor

from mitra import finch, gemini, market, store

NEWS_PROMPT = """You are a market analyst. Below are the latest news headlines for some {market_name} assets.
For each asset give a news sentiment score from -1 (very negative) to +1 (very positive) based ONLY on these headlines,
one short reason a beginner understands (max 20 words), and any big upcoming event mentioned (results, launch, policy) or "".
If an asset has no relevant headline, give 0 and say "No major news.".
Also give one sentence on the overall mood across these headlines.
{headlines}
Return JSON: {{"market_mood": "...", "assets": [{{"ticker": "SAME TICKER AS GIVEN", "sentiment": 0.3,
"reason": "...", "event": "..."}}]}}"""

DEEP_PROMPT = """You are a careful equity/crypto research analyst. The trader is unsure about: {tickers}
({market_name}). Using the technical context and the recent headlines below, give for each: the bull case
(1 sentence), the bear case (1 sentence), the key risk in the next 2 weeks (1 sentence), and your conviction to BUY now
from 0 to 1.
Technical context: {context}
Headlines:
{headlines}
Return JSON: {{"assets": [{{"ticker": "SAME TICKER AS GIVEN", "bull": "...", "bear": "...", "risk": "...",
"conviction": 0.5}}]}}"""


def _safe_headlines(t: str, n: int) -> list[dict]:
    try:
        return market.headlines(t, n)
    except Exception as err:
        logging.warning("headlines failed for %s: %s", t, err)
        return []


def gather_headlines(tickers: list[str], n: int = 3) -> dict[str, list[dict]]:
    """Fetch every asset's headlines at the same time (much faster than one by one)."""
    with ThreadPoolExecutor(max_workers=8) as pool:
        return dict(zip(tickers, pool.map(lambda t: _safe_headlines(t, n), tickers)))


def headline_text(news_by_ticker: dict[str, list[dict]]) -> str:
    lines = []
    for t, items in news_by_ticker.items():
        lines.append(f"{t}:")
        for h in items or []:
            lines.append(f"  - [{h.get('date', '')}] {h['title']} ({h.get('source') or 'news'})"
                         + (f": {h['summary'][:160]}" if h.get("summary") else ""))
        if not items:
            lines.append("  - (no recent headlines)")
    return "\n".join(lines)


def insights_path(req_id: str):
    return store.WORK / "insights" / f"{req_id}.json"


def news(market_code: str, tickers: list[str]) -> tuple[dict, list[dict], dict]:
    """Yahoo Finance headlines -> Gemini reads them and scores sentiment per asset."""
    cfg = market.MARKETS[market_code]
    by_ticker = gather_headlines(tickers)
    sources = [{"title": f"{h['title']} ({h.get('source') or 'news'})", "url": h["url"]}
               for items in by_ticker.values() for h in items[:1] if h.get("url")]
    if not any(by_ticker.values()):
        return {}, [], by_ticker
    try:
        data = gemini.ask_json(NEWS_PROMPT.format(market_name=cfg["name"], headlines=headline_text(by_ticker)),
                               fast=True)
    except Exception as err:  # quota / network: keep going with technicals + raw headlines
        logging.warning("news check failed: %s", err)
        data = {}
    return (data if isinstance(data, dict) else {}), sources, by_ticker


def analyse(market_code: str, tickers: list[str], req_id: str) -> dict:
    cfg = market.MARKETS[market_code]
    def safe_tech(t):
        try:
            return market.technicals(t)
        except Exception as err:
            logging.warning("price data failed for %s: %s", t, err)
            return None

    # prices for every asset + the benchmark + the Finch marketplace search, all at the same time
    with ThreadPoolExecutor(max_workers=10) as pool:
        finch_job = pool.submit(finch.discover, market_code)
        bench_job = pool.submit(safe_tech, cfg["benchmark"])
        techs = list(pool.map(safe_tech, tickers))
    rows = [r for r in techs if r]
    failed = [t for t, r in zip(tickers, techs) if not r]
    if not rows:
        raise RuntimeError("Could not load prices for any of the selected assets.")

    news_data, sources, by_ticker = news(market_code, [r["ticker"] for r in rows])
    scored = {str(a.get("ticker", "")).upper(): a for a in news_data.get("assets", []) if isinstance(a, dict)}
    for r in rows:
        n = scored.get(r["ticker"].upper(), {})
        try:
            sentiment = max(-1.0, min(1.0, float(n.get("sentiment", 0) or 0)))
        except (TypeError, ValueError):
            sentiment = 0.0
        heads = by_ticker.get(r["ticker"]) or []
        r["headlines"] = heads[:3]
        r["news_sentiment"] = round(sentiment, 2)
        r["news_reason"] = str(n.get("reason", "") or
                               (f"Latest: {heads[0]['title']}" if heads else "No recent headlines found."))
        r["event"] = str(n.get("event", "") or "")
        # combined score: 60% price action, 40% news (price action only if there is no news read)
        r["score"] = round(0.6 * r["tech_score"] + 0.4 * sentiment * 100) if n else r["tech_score"]
        r["view"] = "Bullish" if r["score"] >= 25 else "Bearish" if r["score"] <= -25 else "Neutral"
    rows.sort(key=lambda r: -r["score"])

    bench = bench_job.result()
    benchmark = {"ticker": cfg["benchmark"], "name": cfg["benchmark_name"]}
    if bench:
        benchmark.update(price=bench["price"], change_1d=bench["change_1d"], change_20d=bench["change_20d"])

    insights = {
        "req": req_id, "market": market_code, "market_name": cfg["name"], "currency": cfg["currency"],
        "created": store.now(), "assets": rows, "failed": failed, "benchmark": benchmark,
        "market_mood": str(news_data.get("market_mood", "") or ""), "sources": sources[:6], "deep_dive": {},
        "finch": finch_job.result(),  # sponsor: related agents/skills on the Finch marketplace
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
    heads = {t: rows[t].get("headlines") or [] for t in tickers}
    sources = []
    try:
        data = gemini.ask_json(DEEP_PROMPT.format(
            tickers=", ".join(tickers), market_name=insights["market_name"], context=context,
            headlines=headline_text(heads)), fast=True)
    except Exception as err:
        logging.warning("deep dive failed: %s", err)
        data = {}
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
