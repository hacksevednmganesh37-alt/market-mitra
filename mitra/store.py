"""Small JSON store shared by the agents and the web app (requests, agent conversation)."""
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
REQ_DIR = WORK / "requests"
STALE_MINUTES = 15


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text()) if path.exists() else default
    except json.JSONDecodeError:
        return default


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # write to a temp file and swap it in, so a reader never sees a half-written file
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    tmp.replace(path)


def valid_id(req_id: str) -> bool:
    return bool(req_id) and len(req_id) <= 40 and all(c.isalnum() or c == "-" for c in req_id)


def save_request(r: dict) -> None:
    write_json(REQ_DIR / f"{r['id']}.json", r)


def load_request(req_id: str) -> dict | None:
    if not valid_id(req_id):
        return None
    return read_json(REQ_DIR / f"{req_id}.json", None)


def update_request(req_id: str, **fields) -> dict | None:
    r = load_request(req_id)
    if r is None:
        return None
    r.update(fields)
    save_request(r)
    return r


def log_message(req_id: str, sender: str, to: str, message: str) -> None:
    """Keep the agent-to-agent conversation so the web app can show it live."""
    r = load_request(req_id)
    if r is None:
        return
    r.setdefault("events", []).append({"time": now(), "from": sender, "to": to, "message": message})
    save_request(r)


def is_stale(req_id: str) -> bool:
    """True for a request that is unknown, already answered, or too old.

    After a restart BAND re-delivers old messages; without this check the agents
    would redo every old request before getting to the person waiting now."""
    if not req_id:
        return False
    r = load_request(req_id)
    if not r or r.get("status") in ("done", "error"):
        return True
    try:
        created = datetime.fromisoformat(r["created"])
    except (KeyError, ValueError, TypeError):
        return True
    return (datetime.now(timezone.utc) - created).total_seconds() > STALE_MINUTES * 60


def fail_request(req_id: str, sender: str, message: str) -> None:
    """Tell the waiting user something went wrong, instead of leaving them waiting."""
    if load_request(req_id) is None:
        return
    log_message(req_id, sender, "Desk", message)
    update_request(req_id, status="error", error=message)
