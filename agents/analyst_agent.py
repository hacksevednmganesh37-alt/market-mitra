"""MARKET ANALYST - gathers market data, tracks trends, finds opportunities, hands them to the Trader.

Messages it understands (over BAND):
  analyse market=IN|US|CRYPTO req=<id>          (from Mitra Desk, the web app)
  NEED_MORE market=IN tickers=TCS.NS,INFY.NS req=<id>   (from Market Trader: "I'm unsure, look deeper")
"""
import asyncio

from mitra import analyst, store
from mitra.band_helper import ANALYST_NAME, TRADER_NAME, is_agent, parse_command, run_agent


async def handle(sender: str, text: str, send) -> None:
    cmd = parse_command(text)
    action = cmd["action"]
    req = cmd.get("req", "")
    human = sender and not is_agent(sender)
    if store.is_stale(req):
        return  # old message re-delivered after a restart: skip it

    if action in ("ANALYSE", "ANALYZE"):
        request = store.load_request(req)
        if not request:
            if human:
                await send("Please start a run from the Market Mitra web app.", [sender])
            return
        m = request["market"]
        tickers = request["tickers"]
        store.log_message(req, ANALYST_NAME, "markets + news",
                          f"Pulling 6 months of prices for {len(tickers)} assets and reading the latest news.")
        try:
            ins = await asyncio.to_thread(analyst.analyse, m, tickers, req)
        except Exception:
            store.fail_request(req, ANALYST_NAME, "Sorry, I couldn't load market data right now. Please try again in a minute.")
            raise
        top = ", ".join(f"{r['ticker']} {r['score']:+}" for r in ins["assets"][:3])
        bullish = sum(1 for r in ins["assets"] if r["view"] == "Bullish")
        store.log_message(req, ANALYST_NAME, TRADER_NAME,
                          f"Analysed {len(ins['assets'])} assets: {bullish} look bullish. Top ideas: {top}. "
                          f"{ins['market_mood']}".strip())
        await send(f"@{TRADER_NAME} INSIGHTS_READY market={m} round=1 req={req}  (top: {top})", [TRADER_NAME])

    elif action == "NEED_MORE":
        tickers = [t for t in cmd.get("tickers", "").split(",") if t]
        try:
            await asyncio.to_thread(analyst.deep_dive, req, tickers)
        except Exception:
            store.fail_request(req, ANALYST_NAME, "Sorry, my second look failed. Please try again in a minute.")
            raise
        store.log_message(req, ANALYST_NAME, TRADER_NAME,
                          f"Took a deeper look at {', '.join(tickers)}: bull case, bear case and key risk added.")
        await send(f"@{TRADER_NAME} INSIGHTS_READY market={cmd.get('market', '')} round=2 req={req}", [TRADER_NAME])

    elif human:
        await send("I'm the Market Analyst. Start a run from the Market Mitra web app.", [sender])
    # messages from other agents that are not commands are ignored on purpose (no reply loops)


if __name__ == "__main__":
    run_agent("analyst", handle)
