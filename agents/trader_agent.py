"""MARKET TRADER - uses the Analyst's insights to make SIMULATED trades, through hard risk rules.

Messages it understands (over BAND):
  INSIGHTS_READY market=IN round=1|2 req=<id>   (from Market Analyst)
If it is unsure about some assets in round 1 it asks the Analyst:  NEED_MORE tickers=...
When done it tells the web app:  @Mitra Desk TRADES_DONE req=<id>
"""
import asyncio
import logging

from mitra import analyst, lessons, market, portfolio, store, trader
from mitra.band_helper import ANALYST_NAME, DESK_NAME, TRADER_NAME, is_agent, parse_command, run_agent


def plan_path(req: str):
    return store.WORK / "plans" / f"{req}.json"


async def finish(req: str, request: dict, insights: dict, plan: dict, send) -> None:
    m = insights["market"]
    p = portfolio.load(m)
    prices = {r["ticker"]: r["price"] for r in insights["assets"]}
    # prices for held assets that are not in today's watchlist
    for t in p["positions"]:
        if t not in prices:
            try:
                prices[t] = await asyncio.to_thread(market.last_price, t)
            except Exception:
                pass
    bench_price = insights.get("benchmark", {}).get("price")
    if p.get("start_benchmark") is None and bench_price:
        p["start_benchmark"] = bench_price

    exits = trader.auto_exits(p, prices)
    done = trader.execute(p, exits, req)
    checked = trader.risk_check(plan, insights, p, request["risk"])
    vetoed = [d for d in checked if d["status"] == "vetoed"]
    approved = [d for d in checked if d["status"] == "approved"]
    store.log_message(req, "Risk rules", TRADER_NAME,
                      f"Checked {len(approved) + len(vetoed)} trade ideas against {request['risk']} risk limits: "
                      f"{len(approved)} approved, {len(vetoed)} vetoed"
                      + (f" ({'; '.join(d['ticker'] + ': ' + d['veto'] for d in vetoed[:3])})" if vetoed else "") + ".")
    done += trader.execute(p, checked, req)
    p["history"].append({"time": store.now(), "equity": portfolio.equity(p, prices), "benchmark": bench_price})
    portfolio.save(p)

    for d in exits + checked:
        d["lesson"] = lessons.for_decision(d)
    result = {"decisions": exits + checked, "trades": done, "engine": plan.get("engine"),
              "scorecard": portfolio.scorecard(p, prices, bench_price), "insights": insights}
    store.update_request(req, status="done", result=result)
    buys = [t for t in done if t["side"] == "BUY"]
    sells = [t for t in done if t["side"] == "SELL"]
    store.log_message(req, TRADER_NAME, DESK_NAME,
                      f"Placed {len(buys)} simulated buy(s) and {len(sells)} sell(s). "
                      f"Portfolio {insights['currency']}{result['scorecard']['equity']:,.2f} "
                      f"({result['scorecard']['return_pct']:+.2f}% since start).")
    try:  # the web app watches the shared store, so this note to the room is informational
        await send(f"@{DESK_NAME} TRADES_DONE req={req}", [DESK_NAME])
    except Exception as err:
        logging.warning("could not post TRADES_DONE: %s", err)


async def handle(sender: str, text: str, send) -> None:
    cmd = parse_command(text)
    action = cmd["action"]
    req = cmd.get("req", "")
    human = sender and not is_agent(sender)
    if store.is_stale(req):
        return  # old message re-delivered after a restart: skip it

    if action == "INSIGHTS_READY":
        request = store.load_request(req)
        insights = store.read_json(analyst.insights_path(req), None)
        if not request or not insights:
            return
        round_no = int(cmd.get("round", 1) or 1)
        try:
            if round_no == 1:
                p = portfolio.load(insights["market"])
                store.log_message(req, TRADER_NAME, "portfolio",
                                  f"Reviewing {len(insights['assets'])} ideas against my portfolio "
                                  f"({len(p['positions'])} open positions, {request['risk']} risk).")
                plan = await asyncio.to_thread(trader.decide, insights, p, request["risk"])
                store.write_json(plan_path(req), plan)
                if plan["unsure"]:
                    # Agent-to-agent step: the Trader asks the Analyst for a deeper look before risking money.
                    store.log_message(req, TRADER_NAME, ANALYST_NAME,
                                      f"I'm unsure about {', '.join(plan['unsure'])}. Can you dig deeper before I decide?")
                    await send(f"@{ANALYST_NAME} NEED_MORE market={insights['market']} "
                               f"tickers={','.join(plan['unsure'])} req={req}", [ANALYST_NAME])
                    return
            else:
                plan = store.read_json(plan_path(req), None) or {"decisions": [], "unsure": []}
                plan = trader.apply_deep_dive(plan, insights)
            await finish(req, request, insights, plan, send)
        except Exception:
            store.fail_request(req, TRADER_NAME, "Sorry, I couldn't finish the trades right now. Please try again in a minute.")
            raise

    elif human:
        await send("I'm the Market Trader. I act on the Market Analyst's insights - start a run from the web app.", [sender])
    # non-command messages from agents are ignored on purpose (no reply loops)


if __name__ == "__main__":
    run_agent("trader", handle)
