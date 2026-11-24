"""MITRA DESK - the web app.

The user picks a market (NSE / US / crypto), the assets and a risk level.
Mitra Desk saves the request and posts it into the BAND room, @mentioning the Market Analyst.
Market Analyst -> Market Trader (-> Market Analyst if the Trader wants a deeper look) -> trades.
The page polls /api/run/<id> and shows the agents' conversation live, then the trades and portfolio.

Run:  uv run uvicorn web.server:app --host 0.0.0.0 --port 8000
"""
import json
import os
import urllib.error
import urllib.request
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from mitra import market, portfolio, replay, store
from mitra.band_helper import ANALYST_NAME, DESK_NAME

STATIC = Path(__file__).resolve().parent / "static"

ROOM_ID = os.environ.get("MITRA_ROOM_ID", "e103bc88-242e-4edc-bd19-103a1eb7ada8")
ANALYST_ID = os.environ.get("MITRA_ANALYST_ID", "")
# The Desk posts into the room with its own key if it has one, otherwise with the Trader's key.
DESK_KEY = os.environ.get("MITRA_DESK_KEY") or os.environ.get("MITRA_TRADER_KEY", "")
BAND_BASES = [b for b in [os.environ.get("BAND_API_URL"), "https://api.band.ai/api/v1", "https://app.band.ai/api/v1"] if b]

# On a single-container host (Render, Hugging Face...) set AGENTS_IN_PROCESS=1 to run the
# Market Analyst and Market Trader inside this web process: one process uses far less memory.
AGENTS_IN_PROCESS = os.environ.get("AGENTS_IN_PROCESS") == "1"
AGENT_STATUS: dict[str, str] = {}


async def keep_agent_running(name: str, module: str) -> None:
    import asyncio
    import importlib
    import logging

    from mitra.band_helper import serve_agent

    handler = importlib.import_module(module).handle
    while True:
        AGENT_STATUS[name] = "running"
        try:
            await serve_agent(name, handler)
            AGENT_STATUS[name] = "stopped, restarting"
        except asyncio.CancelledError:
            raise
        except BaseException as err:  # includes SystemExit from a missing config
            logging.exception("%s agent crashed", name)
            AGENT_STATUS[name] = f"error: {err!r}"[:200]
        await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(_app):
    import asyncio

    tasks = []
    if AGENTS_IN_PROCESS:
        tasks = [asyncio.create_task(keep_agent_running("analyst", "agents.analyst_agent")),
                 asyncio.create_task(keep_agent_running("trader", "agents.trader_agent"))]
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="Market Mitra", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class RunRequest(BaseModel):
    market: str = Field(pattern="^(IN|US|CRYPTO)$")
    tickers: list[str] = []
    risk: str = Field(default="medium", pattern="^(low|medium|high)$")


class ResetRequest(BaseModel):
    capital: float | None = Field(default=None, gt=0, le=1e9)


def post_to_band(content: str) -> None:
    body = json.dumps({"message": {"content": content,
                                   "mentions": [{"id": ANALYST_ID, "name": ANALYST_NAME}]}}).encode()
    last_error = None
    for base in BAND_BASES:
        req = urllib.request.Request(
            f"{base}/agent/chats/{ROOM_ID}/messages", data=body, method="POST",
            headers={"X-API-Key": DESK_KEY, "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                if resp.status in (200, 201):
                    return
                last_error = f"HTTP {resp.status}"
        except urllib.error.HTTPError as err:
            last_error = f"HTTP {err.code}: {err.read()[:200]!r}"
        except urllib.error.URLError as err:
            last_error = str(err.reason)
    raise RuntimeError(f"Could not post to BAND ({last_error})")


@app.get("/")
def home():
    return FileResponse(STATIC / "index.html")


@app.get("/api/markets")
def markets():
    return [{"code": k, "name": v["name"], "currency": v["currency"], "benchmark": v["benchmark_name"],
             "watchlist": v["watchlist"], "capital": portfolio.DEFAULT_CAPITAL[k]} for k, v in market.MARKETS.items()]


@app.post("/api/run")
def create_run(r: RunRequest):
    cfg = market.MARKETS[r.market]
    allowed = set(cfg["watchlist"])
    tickers = [t for t in dict.fromkeys(x.strip().upper() for x in r.tickers) if t in allowed] or cfg["watchlist"]
    req_id = uuid.uuid4().hex[:10]
    store.save_request({"id": req_id, "market": r.market, "tickers": tickers, "risk": r.risk,
                        "status": "working", "events": [], "created": store.now()})
    store.log_message(req_id, DESK_NAME, ANALYST_NAME,
                      f"New run: {cfg['name']}, {len(tickers)} assets, {r.risk} risk. Please find opportunities.")
    try:
        post_to_band(f"@{ANALYST_NAME} analyse market={r.market} req={req_id}")
    except RuntimeError as err:
        store.update_request(req_id, status="error", error=str(err))
        raise HTTPException(502, str(err))
    return {"id": req_id}


@app.post("/api/replay")
def run_replay(r: RunRequest):
    """Replay the last 7 trading days with the same scoring, trader rules and risk rules (prices only)."""
    cfg = market.MARKETS[r.market]
    allowed = set(cfg["watchlist"])
    tickers = [t for t in dict.fromkeys(x.strip().upper() for x in r.tickers) if t in allowed] or cfg["watchlist"]
    try:
        return replay.replay(r.market, tickers, r.risk)
    except Exception as err:
        raise HTTPException(502, f"Replay failed: {err}")


@app.get("/api/run/{req_id}")
def get_run(req_id: str):
    r = store.load_request(req_id)
    if not r:
        raise HTTPException(404, "Unknown run")
    return r


@app.get("/api/portfolio/{market_code}")
def get_portfolio(market_code: str):
    if market_code not in market.MARKETS:
        raise HTTPException(404, "Unknown market")
    p = portfolio.load(market_code)
    return {"market": market_code, "currency": p["currency"], "start_capital": p["start_capital"],
            "cash": p["cash"], "positions": p["positions"], "trades": p["trades"][-30:], "history": p["history"][-60:]}


@app.post("/api/portfolio/{market_code}/reset")
def reset_portfolio(market_code: str, body: ResetRequest):
    if market_code not in market.MARKETS:
        raise HTTPException(404, "Unknown market")
    portfolio.reset(market_code, body.capital)
    return {"ok": True}


@app.get("/api/health")
def health():
    return {"ok": True, "room": ROOM_ID, "analyst": ANALYST_NAME, "analyst_id_set": bool(ANALYST_ID),
            "poster_key_set": bool(DESK_KEY), "agents_in_process": AGENTS_IN_PROCESS,
            "agents": AGENT_STATUS}
