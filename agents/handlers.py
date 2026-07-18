#!/usr/bin/env python3
"""
AetherOS agent local handlers.

Each fleet peer that owns a *local* side-effect implements handle(agent_id, text).
Dispatch calls these for T0/T1 (local-safe / local-side-effect) commands so the
fleet actually *does* something instead of only logging.

T2 (external) commands are NOT handled here — they wait in the Outbox for the
human SEND. This file never touches the network or any cloud key.
"""
from __future__ import annotations
import json, re, time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent  # project root (handlers.py lives in agents/)
AGENT_LOG = HERE / "agent_activity.json"
QUESTS = HERE / "quests.json"
THEME_REQ = HERE / "theme_request.json"


def _log(agent_id: str, text: str, detail: str):
    rows = []
    if AGENT_LOG.exists():
        try:
            rows = json.loads(AGENT_LOG.read_text(encoding="utf-8"))
        except Exception:
            rows = []
    rows.insert(0, {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "agent": agent_id,
                   "text": text, "detail": detail})
    rows = rows[:300]
    AGENT_LOG.write_text(json.dumps(rows, indent=2), encoding="utf-8")


def _append_quest(text: str) -> str:
    # pull a quest name: "add quest <name>" or "new quest: <name>"
    m = re.search(r"(?:add|new)\s*quest\s*:?\s*(.+)", text, re.I)
    name = m.group(1).strip().strip(".\"") if m else text.strip()
    name = name[:120]
    quests = []
    if QUESTS.exists():
        try:
            quests = json.loads(QUESTS.read_text(encoding="utf-8"))
        except Exception:
            quests = []
    quests.insert(0, {"name": name, "added": time.strftime("%Y-%m-%d %H:%M:%S"), "done": False})
    quests = quests[:200]
    QUESTS.write_text(json.dumps(quests, indent=2), encoding="utf-8")
    return f"quest logged: {name}"


def _theme_request(text: str) -> str:
    # capture explicit color/theme intent; otherwise just record the wish
    colors = re.findall(r"#?[0-9a-fA-F]{6}", text)
    THEME_REQ.write_text(json.dumps({
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "text": text, "colors": colors
    }, indent=2), encoding="utf-8")
    return "theme request recorded" + (f" ({colors[0]})" if colors else "")


def handle(agent_id: str, text: str) -> dict:
    """Perform the local side-effect for a T0/T1 command. Returns {ok, detail}."""
    try:
        if agent_id == "aetherquest":
            detail = _append_quest(text)
        elif agent_id == "fairyos":
            detail = _theme_request(text)
        elif agent_id == "steward":
            detail = "steward probe noted"
        elif agent_id == "brain":
            detail = "knowledge note recorded"
        elif agent_id == "companion":
            detail = "companion reflection logged"
        else:
            detail = f"{agent_id} handled (logged)"
        _log(agent_id, text, detail)
        return {"ok": True, "detail": detail}
    except Exception as e:
        return {"ok": False, "detail": f"handler error: {e}"}
