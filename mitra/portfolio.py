"""Paper (simulated) portfolio - one per market. No real money, no real orders."""
from mitra import market, store

DEFAULT_CAPITAL = {"IN": 50000.0, "US": 10000.0, "CRYPTO": 10000.0}


def path(market_code: str):
    return store.WORK / "portfolio" / f"{market_code}.json"


def load(market_code: str) -> dict:
    p = store.read_json(path(market_code), None)
    if p is None:
        p = new(market_code, DEFAULT_CAPITAL[market_code])
    return p


def new(market_code: str, capital: float) -> dict:
    cfg = market.MARKETS[market_code]
    return {"market": market_code, "currency": cfg["currency"], "start_capital": capital, "cash": capital,
            "positions": {}, "trades": [], "history": [], "start_benchmark": None, "created": store.now()}


def save(p: dict) -> None:
    store.write_json(path(p["market"]), p)


def reset(market_code: str, capital: float | None = None) -> dict:
    p = new(market_code, capital or DEFAULT_CAPITAL[market_code])
    save(p)
    return p


def equity(p: dict, prices: dict[str, float]) -> float:
    held = sum(pos["qty"] * prices.get(t, pos["avg_price"]) for t, pos in p["positions"].items())
    return round(p["cash"] + held, 2)


def scorecard(p: dict, prices: dict[str, float], benchmark_price: float | None) -> dict:
    eq = equity(p, prices)
    port_ret = (eq / p["start_capital"] - 1) * 100 if p["start_capital"] else 0.0
    bench_ret = None
    if benchmark_price and p.get("start_benchmark"):
        bench_ret = (benchmark_price / p["start_benchmark"] - 1) * 100
    positions = []
    for t, pos in p["positions"].items():
        price = prices.get(t, pos["avg_price"])
        positions.append({**pos, "ticker": t, "price": round(price, 4),
                          "value": round(pos["qty"] * price, 2),
                          "pnl": round((price - pos["avg_price"]) * pos["qty"], 2),
                          "pnl_pct": round((price / pos["avg_price"] - 1) * 100, 2) if pos["avg_price"] else 0.0})
    closed = [t for t in p["trades"] if t["side"] == "SELL" and t.get("pnl") is not None]
    wins = sum(1 for t in closed if t["pnl"] > 0)
    return {
        "equity": eq, "cash": round(p["cash"], 2), "start_capital": p["start_capital"],
        "return_pct": round(port_ret, 2), "benchmark_return_pct": None if bench_ret is None else round(bench_ret, 2),
        "beating_benchmark": None if bench_ret is None else port_ret > bench_ret,
        "positions": positions, "closed_trades": len(closed),
        "win_rate": round(wins / len(closed) * 100) if closed else None,
        "realised_pnl": round(sum(t["pnl"] for t in closed), 2),
    }
