"""TRADER work: turn the Analyst's insights into simulated trades, through hard risk rules."""
import logging
import math

from mitra import gemini, market, portfolio, store

RISK = {
    #          max share of equity per position, max open positions, min confidence, max stop distance
    "low":    {"max_pos": 0.10, "max_positions": 4, "min_conf": 0.65, "max_stop": 0.05, "max_rsi": 72},
    "medium": {"max_pos": 0.20, "max_positions": 5, "min_conf": 0.55, "max_stop": 0.08, "max_rsi": 78},
    "high":   {"max_pos": 0.30, "max_positions": 6, "min_conf": 0.45, "max_stop": 0.12, "max_rsi": 85},
}

DECIDE_PROMPT = """You are a disciplined swing trader (holding days to weeks) managing a SIMULATED {market_name}
portfolio. Risk profile: {risk}. Cash: {cur}{cash:,.2f}. Equity: {cur}{equity:,.2f}.
Current positions: {positions}
Analyst insights (score -100..100 combines price action and news):
{assets}
Market mood: {mood}
Rules: only BUY assets with a clear edge; SELL held assets whose outlook turned negative; otherwise HOLD.
Every BUY needs a stop_loss below the price and a target above it (use ATR as a guide).
allocation_pct is the share of equity for a BUY (max {max_pos:.0f}).
Put assets where you are genuinely unsure (could go either way) in "unsure" (max 3).
Explain each decision in one plain sentence a beginner understands.
Return JSON: {{"decisions": [{{"ticker": "SAME TICKER", "action": "BUY|SELL|HOLD", "confidence": 0.7,
"allocation_pct": 15, "stop_loss": 0.0, "target": 0.0, "reason": "..."}}], "unsure": ["TICKER"]}}"""


def asset_line(r: dict) -> str:
    return (f"- {r['ticker']}: price {r['price']}, 1d {r['change_1d']}%, 20d {r['change_20d']}%, RSI {r['rsi']}, "
            f"ATR {r['atr']}, trend notes: {', '.join(r['tech_notes'])}; news {r['news_sentiment']:+} "
            f"({r['news_reason']}); event: {r['event'] or 'none'}; score {r['score']} ({r['view']})")


def rule_based(insights: dict, p: dict) -> dict:
    """Backup decisions when Gemini is unavailable: simple, transparent rules."""
    decisions = []
    for r in insights["assets"]:
        held = r["ticker"] in p["positions"]
        if not held and r["score"] >= 35:
            decisions.append({"ticker": r["ticker"], "action": "BUY", "confidence": round(min(0.9, 0.5 + r["score"] / 200), 2),
                              "allocation_pct": 15, "stop_loss": r["price"] - 2 * r["atr"], "target": r["price"] + 3 * r["atr"],
                              "reason": f"Strong combined score {r['score']}: {r['tech_notes'][0]}."})
        elif held and r["score"] <= -25:
            decisions.append({"ticker": r["ticker"], "action": "SELL", "confidence": 0.7,
                              "reason": f"Outlook turned negative (score {r['score']})."})
        else:
            decisions.append({"ticker": r["ticker"], "action": "HOLD", "confidence": 0.5,
                              "reason": f"No clear edge right now (score {r['score']})."})
    unsure = [r["ticker"] for r in insights["assets"] if 20 <= r["score"] < 35 and r["ticker"] not in p["positions"]][:3]
    return {"decisions": decisions, "unsure": unsure, "engine": "rules"}


def decide(insights: dict, p: dict, risk: str) -> dict:
    prices = {r["ticker"]: r["price"] for r in insights["assets"]}
    eq = portfolio.equity(p, prices)
    positions = ", ".join(f"{t} qty {pos['qty']} @ {pos['avg_price']}" for t, pos in p["positions"].items()) or "none"
    try:
        data = gemini.ask_json(DECIDE_PROMPT.format(
            market_name=insights["market_name"], risk=risk, cur=insights["currency"], cash=p["cash"], equity=eq,
            positions=positions, assets="\n".join(asset_line(r) for r in insights["assets"]),
            mood=insights.get("market_mood") or "unknown", max_pos=RISK[risk]["max_pos"] * 100))
        known = set(prices)
        decisions = [d for d in data.get("decisions", []) if isinstance(d, dict) and d.get("ticker") in known]
        if not decisions:
            raise ValueError("no usable decisions")
        unsure = [t for t in data.get("unsure", []) if t in known][:3]
        return {"decisions": decisions, "unsure": unsure, "engine": "gemini"}
    except Exception as err:
        logging.warning("Gemini decision failed (%s); using rule-based trader", err)
        return rule_based(insights, p)


def apply_deep_dive(plan: dict, insights: dict) -> dict:
    """After the Analyst's second look: keep a BUY only if the Analyst's conviction is high enough."""
    for d in plan["decisions"]:
        dd = insights.get("deep_dive", {}).get(d["ticker"])
        if not dd:
            continue
        try:
            conv = float(dd.get("conviction") or 0)
        except (TypeError, ValueError):
            conv = 0.0
        d["deep_dive"] = dd
        if d.get("action") == "BUY" and conv < 0.55:
            d["action"], d["reason"] = "HOLD", f"Analyst's second look was not convincing ({conv:.0%}): {dd.get('risk') or ''}".strip()
        elif d.get("action") == "HOLD" and conv >= 0.7:
            r = next(a for a in insights["assets"] if a["ticker"] == d["ticker"])
            d.update(action="BUY", confidence=conv, allocation_pct=10,
                     stop_loss=r["price"] - 2 * r["atr"], target=r["price"] + 3 * r["atr"],
                     reason=f"Analyst's second look found a strong case: {dd.get('bull') or ''}".strip())
    return plan


def num(x, default=0.0) -> float:
    try:
        v = float(x)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


COOL_OFF_DAYS = 3


def recently_sold(p: dict, days: int = COOL_OFF_DAYS) -> set[str]:
    """Assets sold in the last few days (based on the trade timestamps)."""
    from datetime import datetime, timedelta, timezone
    since = datetime.now(timezone.utc) - timedelta(days=days)
    out = set()
    for t in p.get("trades", []):
        try:
            when = datetime.fromisoformat(t["time"])
        except (KeyError, ValueError, TypeError):
            continue
        if t.get("side") == "SELL" and when >= since:
            out.add(t["ticker"])
    return out


def risk_check(plan: dict, insights: dict, p: dict, risk: str, cooling: set[str] | None = None) -> list[dict]:
    """The Risk Manager: hard rules no AI decision can override. Fills in qty, may VETO."""
    rules = RISK[risk]
    cooling = recently_sold(p) if cooling is None else cooling
    rows = {r["ticker"]: r for r in insights["assets"]}
    prices = {t: r["price"] for t, r in rows.items()}
    eq = portfolio.equity(p, prices)
    fractional = market.MARKETS[insights["market"]]["fractional"]
    cash = p["cash"]
    open_count = len(p["positions"])
    checked = []
    # sells first (they free up cash and slots)
    order = sorted(plan["decisions"], key=lambda d: {"SELL": 0, "BUY": 1}.get(str(d.get("action")).upper(), 2))
    for d in order:
        d = dict(d)
        action = str(d.get("action", "HOLD")).upper()
        t = d["ticker"]
        r = rows[t]
        price = r["price"]
        d.update(action=action, price=price, status="info", confidence=round(num(d.get("confidence"), 0.5), 2))
        if action == "SELL":
            if t in p["positions"]:
                d.update(status="approved", qty=p["positions"][t]["qty"])
                cash += p["positions"][t]["qty"] * price
                open_count -= 1
            else:
                d.update(action="HOLD", status="info", reason=d.get("reason", "") + " (not held, nothing to sell)")
        elif action == "BUY":
            veto = None
            stop = num(d.get("stop_loss"))
            target = num(d.get("target"))
            if t in p["positions"]:
                veto = "already holding it"
            elif t in cooling:
                veto = f"sold it in the last {COOL_OFF_DAYS} days - cool-off to avoid revenge trading"
            elif open_count >= rules["max_positions"]:
                veto = f"max {rules['max_positions']} open positions for {risk} risk"
            elif d["confidence"] < rules["min_conf"]:
                veto = f"confidence {d['confidence']:.0%} below {rules['min_conf']:.0%} needed for {risk} risk"
            elif r["rsi"] > rules["max_rsi"]:
                veto = f"RSI {r['rsi']} too stretched (limit {rules['max_rsi']})"
            if veto is None:
                # stop-loss must exist, be below price, and not be too far away
                if not (0 < stop < price) or (price - stop) / price > rules["max_stop"]:
                    stop = price * (1 - min(rules["max_stop"], max(0.02, 2 * r["atr"] / price)))
                    d["stop_note"] = "stop-loss set by risk rules"
                if not target > price:
                    target = price + 2 * (price - stop)
                alloc = min(num(d.get("allocation_pct"), 10) / 100, rules["max_pos"])
                budget = min(eq * alloc, cash)
                qty = round(budget / price, 4) if fractional else math.floor(budget / price)
                if qty <= 0:
                    veto = "not enough cash for even one unit"
            if veto:
                d.update(status="vetoed", veto=veto)
            else:
                d.update(status="approved", qty=qty, stop_loss=round(stop, 4), target=round(target, 4),
                         allocation_pct=round(alloc * 100, 1))
                cash -= qty * price
                open_count += 1
        else:
            d.update(action="HOLD")
        checked.append(d)
    return checked


def auto_exits(p: dict, prices: dict[str, float]) -> list[dict]:
    exits = []
    for t, pos in list(p["positions"].items()):
        price = prices.get(t)
        if price is None:
            continue
        if pos.get("stop_loss") and price <= pos["stop_loss"]:
            exits.append({"ticker": t, "action": "SELL", "status": "approved", "qty": pos["qty"], "price": price,
                          "reason": f"Stop-loss {pos['stop_loss']} hit: cutting the loss as planned.", "auto": True})
        elif pos.get("target") and price >= pos["target"]:
            exits.append({"ticker": t, "action": "SELL", "status": "approved", "qty": pos["qty"], "price": price,
                          "reason": f"Target {pos['target']} reached: booking profit.", "auto": True})
    return exits


def execute(p: dict, checked: list[dict], req_id: str) -> list[dict]:
    """Simulated fills at the last price. Nothing is sent to any broker."""
    done = []
    for d in checked:
        if d.get("status") != "approved":
            continue
        t, price, qty = d["ticker"], d["price"], d["qty"]
        if d["action"] == "SELL" and t in p["positions"]:
            pos = p["positions"].pop(t)
            pnl = round((price - pos["avg_price"]) * pos["qty"], 2)
            p["cash"] += pos["qty"] * price
            trade = {"time": store.now(), "req": req_id, "ticker": t, "side": "SELL", "qty": pos["qty"], "price": price,
                     "pnl": pnl, "reason": d.get("reason", "")}
        elif d["action"] == "BUY" and t not in p["positions"] and qty > 0 and qty * price <= p["cash"] + 1e-6:
            p["cash"] -= qty * price
            p["positions"][t] = {"qty": qty, "avg_price": price, "stop_loss": d.get("stop_loss"),
                                 "target": d.get("target"), "opened": store.now(), "reason": d.get("reason", "")}
            trade = {"time": store.now(), "req": req_id, "ticker": t, "side": "BUY", "qty": qty, "price": price,
                     "pnl": None, "reason": d.get("reason", "")}
        else:
            continue
        p["trades"].append(trade)
        done.append(trade)
    p["cash"] = round(p["cash"], 2)
    return done
