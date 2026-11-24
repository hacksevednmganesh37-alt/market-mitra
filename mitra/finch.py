"""Finch (finchtech.ai) - sponsor integration via Finch's public, anonymous read APIs.

The Market Analyst searches Finch's agent/skill marketplace for tools related to the market being
analysed, so a learner can see what specialised agents and skills exist for it.
Read-only: no login, no wallet, nothing is bought, run or downloaded.
Endpoints are the ones used by Finch's own discovery helper
(github.com/FinchipAI/how-to-use-finchtech-cli, scripts/finch_discover.py).
"""
import json
import logging
import os
import urllib.parse
import urllib.request

BASE = os.environ.get("FINCH_BASE_URL", "https://www.finchtech.ai").rstrip("/")
USER_AGENT = "market-mitra/0.1 (+https://github.com/hacksevednmganesh37-alt/market-mitra)"
QUERIES = {
    "IN": "indian stock market analysis",
    "US": "us stock analysis",
    "CRYPTO": "crypto trading analysis",
}


def _get(path: str, params: dict) -> dict:
    query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    req = urllib.request.Request(f"{BASE}{path}?{query}",
                                 headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


def _clip(text, n=180) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def discover(market_code: str, limit: int = 3) -> dict:
    """Top Finch agents and skills for this market. Never raises: returns an empty result on failure."""
    q = QUERIES.get(market_code, "stock market analysis")
    out = {"query": q, "agents": [], "skills": [], "source": BASE}
    try:
        page = _get("/api/market/search", {"kind": "agent", "q": q})
        for card in (page.get("items") or [])[:limit]:
            ref = card.get("agentMarketRef") or {}
            vid = ref.get("serviceVersionId")
            out["agents"].append({
                "name": (card.get("name") or "").strip(),
                "summary": _clip(card.get("summary")),
                "category": card.get("category"),
                "url": f"{BASE}/market/chips/agent-{vid}" if vid else f"{BASE}/market/explore",
            })
    except Exception as err:
        logging.warning("Finch agent search failed: %s", err)
    try:
        page = _get("/api/skills/catalog", {"q": q})
        for card in (page.get("items") or [])[:limit]:
            slug = card.get("slug") or ""
            out["skills"].append({
                "name": (card.get("name") or "").strip(),
                "summary": _clip(card.get("summary")),
                "category": card.get("category"),
                "url": f"{BASE}/market/chips/{urllib.parse.quote(slug)}" if slug else f"{BASE}/market/explore",
            })
    except Exception as err:
        logging.warning("Finch skill search failed: %s", err)
    return out
