"""Turns a simple `handler(sender, text, send)` function into a BAND remote agent.

Agents only receive messages that @mention them, so every agent-to-agent
message below passes the other agent's name in `mentions`.
"""
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Awaitable, Callable

import yaml
from band import Agent, configure_logging
from band.adapters import LangGraphAdapter
from band.runtime.formatters import strip_leading_mentions
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "agent_config.yaml"

# Names must match exactly the agent names in BAND (set them in scripts/start_all.sh).
ANALYST_NAME = os.environ.get("MITRA_ANALYST_NAME", "Market Analyst")
TRADER_NAME = os.environ.get("MITRA_TRADER_NAME", "Market Trader")
DESK_NAME = os.environ.get("MITRA_DESK_NAME", "Mitra Desk")
AGENT_NAMES = {ANALYST_NAME, TRADER_NAME, DESK_NAME}


def is_agent(name: str) -> bool:
    """True if the message came from one of our own agents (never auto-reply to these: avoids loops)."""
    return name.strip() in AGENT_NAMES

SENDER = re.compile(r"^\[(?P<sender>[^\]]+)\]:\s*(?P<text>.*)$", re.DOTALL)

Send = Callable[[str, list[str]], Awaitable[None]]
Handler = Callable[[str, str, Send], Awaitable[None]]


def extract_messages(content: str) -> list[tuple[str, str]]:
    """BAND SDK 9.x delivers a turn as a preamble + one JSON object per message
    ({"sender_name": ..., "content": ...}). Older formats use "[Sender]: text"."""
    found = []
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("{") and '"content"' in line:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            found.append((str(obj.get("sender_name", "")), str(obj.get("content", ""))))
    if not found:
        match = SENDER.match(content)
        found.append((match.group("sender") if match else "", match.group("text") if match else content))
    return found


def write_config_from_env() -> None:
    """Build agent_config.yaml from Codespaces secrets (so keys never go in git)."""
    config = {}
    for key, prefix in [("analyst", "MITRA_ANALYST"), ("trader", "MITRA_TRADER")]:
        agent_id, api_key = os.environ.get(f"{prefix}_ID"), os.environ.get(f"{prefix}_KEY")
        if agent_id and api_key:
            config[key] = {"agent_id": agent_id, "api_key": api_key}
    if config:
        CONFIG.write_text(yaml.safe_dump(config))


async def serve_agent(config_key: str, handler: Handler) -> None:
    """Connect one agent to BAND and keep handling its messages (runs until cancelled)."""
    write_config_from_env()
    if not CONFIG.exists():
        raise SystemExit(
            "agent_config.yaml not found. Set MITRA_ANALYST_ID / MITRA_ANALYST_KEY / "
            "MITRA_TRADER_ID / MITRA_TRADER_KEY (see README)."
        )
    checkpointer = InMemorySaver()

    def graph_factory(band_tools: list[Any]):
        send_message = next(t for t in band_tools if t.name == "band_send_message")

        async def send(content: str, mentions: list[str]) -> None:
            await send_message.ainvoke({"content": content, "mentions": mentions})

        async def on_message(state: MessagesState) -> dict:
            if not state["messages"]:
                return {"messages": []}
            content = str(state["messages"][-1].content)
            for sender, raw in extract_messages(content):
                text = strip_leading_mentions(raw).strip()
                logging.warning("MITRA got from %r: %r", sender, text[:300])
                try:
                    await handler(sender, text, send)
                except Exception as err:  # tell the room instead of crashing silently
                    logging.exception("handler failed")
                    if sender and not is_agent(sender):
                        await send(f"Sorry, something went wrong: {err}", [sender])
            return {"messages": []}

        graph = StateGraph(MessagesState)
        graph.add_node("on_message", on_message)
        graph.add_edge(START, "on_message")
        graph.add_edge("on_message", END)
        return graph.compile(checkpointer=checkpointer)

    adapter = LangGraphAdapter(graph_factory=graph_factory)
    agent = Agent.from_config(config_key, adapter=adapter)
    await agent.run()


def run_agent(config_key: str, handler: Handler) -> None:
    """Run one agent as its own process (used by scripts/start_all.sh)."""
    import asyncio

    configure_logging(logging.INFO)
    asyncio.run(serve_agent(config_key, handler))


def parse_command(text: str) -> dict:
    """'INSIGHTS_READY market=IN round=1 req=abc (top: TCS)' -> dict."""
    # remove any @mentions of our agents (names have spaces, so do it explicitly)
    for name in AGENT_NAMES:
        text = text.replace(f"@{name}", " ")
    words0 = text.split()
    while words0 and words0[0].startswith("@"):  # BAND may render mentions as @handle or @[id]
        words0.pop(0)
    text = " ".join(words0)
    for leftover in {n.split()[-1] for n in AGENT_NAMES}:  # e.g. "Trader INSIGHTS_READY ..."
        if text.split(" ", 1)[0] == leftover:
            text = text.split(" ", 1)[1] if " " in text else ""
    # drop the human-readable summary we append in brackets: "... (top: TCS, INFY)"
    text = re.sub(r"\s*\([^()]*\)\s*$", "", text)
    requested_by = ""
    if " requested_by=" in text:
        text, requested_by = text.split(" requested_by=", 1)
    words = text.split()
    cmd = {"action": words[0].upper().rstrip(":") if words else "", "args": [],
           "requested_by": requested_by.strip()}
    for w in words[1:]:
        if "=" in w:
            k, v = w.split("=", 1)
            cmd[k.lower()] = v
        else:
            cmd["args"].append(w)
    return cmd
