#!/usr/bin/env python3
"""
AetherOS Mothership — real terminal-level thinking from the Hermes session store.
Reads AppData/Local/hermes/state.db (sessions + messages + reasoning_content),
organizes thoughts by REALM (derived from session title/cwd) and AGENT (model),
and serves them over loopback to the dashboard.

NO fabrication: every thought shown is a verbatim excerpt from the actual store.
"""
from __future__ import annotations
import json, sqlite3, re, os
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

HERMES_DB = Path.home() / "AppData" / "Local" / "hermes" / "state.db"
PORT = 8920

# Map session-title keywords -> realm/agent grouping
REALM_RULES = [
    (r"qi-games|qi games", "QI-Games", "playful-engine"),
    (r"fairy", "Fairy OS", "fairy-shell"),
    (r"crublore|cooking", "Crublore", "craft-skill"),
    (r"runetek|eclipse", "Runetek Eclipse", "game-engine"),
    (r"aetherquest", "AetherQuest", "life-rpg"),
    (r"echo voice|voice", "Echo Voice", "voice-engine"),
    (r"hermes|gateway", "Hermes", "runtime"),
    (r"mist|nyx|lunari|aurelia", "Mist/Nyx", "companion"),
    (r"gbrain|brain", "Brain", "knowledge"),
    (r"aetherdeck|deck", "AetherDeck", "command"),
    (r"ghostline|steward", "Steward", "observer"),
    (r"ally", "Ally Node", "deploy"),
]
def classify(title: str, cwd: str) -> str:
    blob = f"{title or ''} {cwd or ''}".lower()
    for pat, realm, _ in REALM_RULES:
        if re.search(pat, blob):
            return realm
    return "Other"


def get_thoughts(limit_per_realm: int = 8, min_len: int = 30):
    if not HERMES_DB.exists():
        return {"error": f"Hermes DB not found at {HERMES_DB}"}
    c = sqlite3.connect(str(HERMES_DB)); cur = c.cursor()
    # join messages with reasoning to sessions for realm + title + model
    q = """
    SELECT s.title, s.cwd, s.model, m.reasoning_content, m.timestamp, s.id
    FROM messages m JOIN sessions s ON m.session_id = s.id
    WHERE m.reasoning_content IS NOT NULL AND length(m.reasoning_content) > ?
    ORDER BY m.timestamp DESC LIMIT 400
    """
    cur.execute(q, (min_len,))
    rows = cur.fetchall()
    c.close()

    realms: dict[str, list] = {}
    for title, cwd, model, reasoning, ts, sid in rows:
        realm = classify(title, cwd)
        # trim reasoning to first meaningful paragraph
        text = (reasoning or "").strip().replace("\r", "")
        # take first ~280 chars as the "thought"
        snippet = text[:280]
        entry = {
            "realm": realm, "agent": model or "unknown",
            "session": str(sid)[:16], "title": (title or "untitled")[:50],
            "ts": ts, "thought": snippet,
        }
        realms.setdefault(realm, []).append(entry)

    # cap per realm
    out = {}
    for realm, items in realms.items():
        out[realm] = items[:limit_per_realm]
    synth = synthesize(out)
    return {"realms": out, "total_reasoning": len(rows),
            "source": "Hermes state.db (verbatim)", "synthesis": synth}


def synthesize(realms: dict) -> list:
    """Derive a calm steer-card per realm from real thoughts. No invented facts."""
    cards = []
    for realm, items in realms.items():
        if not items:
            continue
        last = items[0]
        # derive an open question only if the text looks unfinished/ambiguous
        txt = last["thought"]
        open_q = None
        low = txt.lower()
        if any(w in low for w in ["ambiguous", "which", "unclear", "not sure", "torn between", "decision", "?"]):
            # take the tail as the open question if it ends mid-thought
            open_q = txt[-140:].strip()
        cards.append({
            "realm": realm,
            "agent": last["agent"],
            "thoughts": len(items),
            "last_ts": last["ts"],
            "last_signal": txt[:160].replace("\n", " "),
            "open_question": open_q,
            "needs_your_call": bool(open_q),
        })
    # sort: realms needing a call first
    cards.sort(key=lambda c: (not c["needs_your_call"], c["realm"]))
    return cards


def get_process_telemetry():
    import subprocess
    try:
        out = subprocess.check_output(["powershell", "-NoProfile",
            "Get-Process python* -ErrorAction SilentlyContinue | Select-Object Id,CPU,WorkingSet,StartTime | ConvertTo-Json"],
            timeout=8)
        procs = json.loads(out) if out.strip() else []
        if isinstance(procs, dict): procs = [procs]
        return [{"pid": p.get("Id"), "cpu": round(p.get("CPU") or 0, 1),
                 "mem_mb": round((p.get("WorkingSet") or 0)/1e6, 1),
                 "started": str(p.get("StartTime"))} for p in procs]
    except Exception as e:
        return [{"error": str(e)[:80]}]


class H(BaseHTTPRequestHandler):
    def _json(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path.rstrip("/") in ("/thoughts", "/mothership"):
            qs = parse_qs(u.query)
            lim = int(qs.get("limit", ["8"])[0])
            self._json(get_thoughts(limit_per_realm=lim))
        elif u.path.rstrip("/") in ("/telemetry",):
            self._json({"processes": get_process_telemetry()})
        elif u.path.rstrip("/") in ("/synthesis", "/deck"):
            self._json(get_thoughts(limit_per_realm=8))
        elif u.path.rstrip("/") == "/health":
            self._json({"ok": True})
        else:
            self.send_response(404); self.end_headers()

    def log_message(self, *a): pass


def main():
    print(f"Mothership on http://127.0.0.1:{PORT}/thoughts (loopback, reads Hermes state.db)")
    HTTPServer(("127.0.0.1", PORT), H).serve_forever()


if __name__ == "__main__":
    main()
