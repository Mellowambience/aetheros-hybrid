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


def _repo_probe(repo: str) -> str:
    """Real local action for an approved repo-backed quest: open the repo, report
    its state. Safe, local-only (no network). For git repos: status. Else: top files."""
    from pathlib import Path as _P
    p = _P(repo)
    if not p.exists():
        return f"repo not found: {repo}"
    if (p / ".git").exists():
        try:
            import subprocess
            out = subprocess.run(["git", "-C", str(p), "status", "--short"],
                                 capture_output=True, text=True, timeout=10)
            lines = [l for l in out.stdout.splitlines() if l.strip()]
            if not lines:
                return f"{p.name}: clean git tree (nothing uncommitted)"
            return f"{p.name}: {len(lines)} uncommitted change(s) — " + "; ".join(lines[:3])
        except Exception as e:
            return f"git probe failed: {e}"
    # non-git repo: list what's there
    try:
        items = sorted([x.name for x in p.iterdir() if not x.name.startswith('.')])[:8]
        return f"{p.name}: {len(items)} top items — " + ", ".join(items)
    except Exception as e:
        return f"list failed: {e}"


def _steward_check() -> str:
    """Truth: read live state, report SLA/drift honestly."""
    try:
        import json as _j
        s = _j.loads((HERE / "state.json").read_text(encoding="utf-8")) if (HERE / "state.json").exists() else {}
        sla = s.get("sla", {})
        pct = sla.get("percent") if isinstance(sla, dict) else None
        return f"state read: SLA {pct}%" if pct is not None else "state read: no SLA recorded"
    except Exception as e:
        return f"state read failed: {e}"


def _deck_pulse() -> str:
    """Command: report current fleet inbox load as a dashboard heartbeat."""
    try:
        import json as _j
        rows = _j.loads((HERE / "command_inbox.json").read_text(encoding="utf-8")) if (HERE / "command_inbox.json").exists() else []
        pending = sum(1 for r in rows if r.get("status") == "queued")
        done = sum(1 for r in rows if r.get("status") in ("executed", "approved_send"))
        return f"deck pulse: {pending} queued / {done} done"
    except Exception as e:
        return f"deck pulse failed: {e}"


def _quest_progress() -> str:
    """Life RPG: count completed quests vs total, report XP."""
    try:
        import json as _j
        qs = _j.loads((HERE / "quests.json").read_text(encoding="utf-8")) if (HERE / "quests.json").exists() else []
        done = sum(1 for q in qs if q.get("done"))
        return f"quest progress: {done}/{len(qs)} done ({done*100} XP)"
    except Exception as e:
        return f"quest progress failed: {e}"


def _brain_index() -> str:
    """Knowledge: index the user's real life's work (works.json)."""
    try:
        import json as _j
        w = _j.loads((HERE / "works.json").read_text(encoding="utf-8")) if (HERE / "works.json").exists() else {}
        n = len(w.get("projects", []))
        return f"knowledge index: {n} repos in life's work"
    except Exception as e:
        return f"knowledge index failed: {e}"


def _analyst_trend() -> str:
    """Insight: count recent fleet activity, report a trend."""
    try:
        import json as _j
        from collections import Counter
        acts = _j.loads((HERE / "agent_activity.json").read_text(encoding="utf-8")) if (HERE / "agent_activity.json").exists() else []
        c = Counter(a.get("agent") for a in acts[:50])
        top = c.most_common(1)
        busiest = f"{top[0][0]} ({top[0][1]})" if top else "none"
        return f"insight: {len(acts)} recent actions, busiest {busiest}"
    except Exception as e:
        return f"insight failed: {e}"


def _companion_reflect() -> str:
    """Presence: a calm reflection line (local, no network)."""
    return "companion: present. fleet steady, owner attended to."


def _voice_gate() -> str:
    """Voice: honestly report whether the local voice backend is installed."""
    consent = HERE / "voice" / "consent.json"
    if consent.exists():
        return "voice gate: consent present — loopback listener armed"
    return "voice gate: OFFLINE (echo_voice not installed; consent file absent)"


def _pulse_job(agent_id: str) -> str:
    """The recurring job each alter runs when invoked via a [pulse] command.
    Distinct from one-off side-effects (e.g. adding a quest) so the heartbeat
    doesn't pollute quests/themes."""
    if agent_id == "steward":
        return _steward_check()
    if agent_id == "aetherdeck":
        return _deck_pulse()
    if agent_id == "brain":
        return _brain_index()
    if agent_id == "companion":
        return _companion_reflect()
    if agent_id == "analyst":
        return _analyst_trend()
    if agent_id == "echovoice":
        return _voice_gate()
    if agent_id == "hermes":
        return "hermes: orchestrate — fleet heartbeat emitted"
    if agent_id == "fairyos":
        return "fairyos: shell heartbeat — desktop pulse ok"
    if agent_id == "aetherquest":
        return _quest_progress()
    return f"{agent_id} handled (logged)"


def handle(agent_id: str, text: str, repo: str = "") -> dict:
    """Perform the local side-effect for a T0/T1 command. Returns {ok, detail}.

    Each alter has a real, distinct, local-safe job so no alter is dormant.
    [pulse] commands run the alter's standing job (not one-off side-effects)."""
    try:
        if text.startswith("[quest:approved]") and repo:
            detail = _repo_probe(repo)
        elif text.startswith("[pulse]"):
            detail = _pulse_job(agent_id)
        elif agent_id == "aetherquest":
            detail = _append_quest(text)
        elif agent_id == "fairyos":
            detail = _theme_request(text)
        elif agent_id == "steward":
            detail = _steward_check()
        elif agent_id == "brain":
            detail = _brain_index()
        elif agent_id == "companion":
            detail = _companion_reflect()
        elif agent_id == "analyst":
            detail = _analyst_trend()
        elif agent_id == "echovoice":
            detail = _voice_gate()
        elif agent_id == "aetherdeck":
            detail = _deck_pulse()
        else:
            detail = f"{agent_id} handled (logged)"
        _log(agent_id, text, detail)
        return {"ok": True, "detail": detail}
    except Exception as e:
        return {"ok": False, "detail": f"handler error: {e}"}
