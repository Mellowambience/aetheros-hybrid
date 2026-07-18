#!/usr/bin/env python3
"""
Fleet Pulse — keeps every alter alive.

Every ALTER_INTERVAL seconds, for each fleet alter, builds a real local command
(queued in command_inbox.json) carrying that alter's standing job, then triggers
dispatch (POST /dispatch) so handlers.py executes it. Result: no alter is ever
dormant; every alter produces real, observable activity + evidence.

Loopback :8915 (health only). Local-first, no network.
"""
from __future__ import annotations
import json, time, uuid, threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import urllib.request

HERE = Path(__file__).resolve().parent
PORT = 8915
INBOX = HERE / "command_inbox.json"
ALTER_INTERVAL = 30  # seconds between full fleet pulses

# Each alter's standing job (the recurring task it owns).
ALTER_JOBS = {
    "hermes":    ("orchestrate: fleet heartbeat — emit health probe to steward", False),
    "steward":    ("truth: read live state, report SLA/drift", False),
    "aetherdeck": ("command: dashboard pulse — report inbox load", False),
    "aetherquest": ("life rpg: report quest progress / XP", False),
    "fairyos":    ("shell: theme heartbeat", False),
    "echovoice":  ("voice: report gate status", False),
    "brain":      ("knowledge: index life's work", False),
    "companion":  ("presence: reflection", False),
    "analyst":    ("insight: trend report", False),
}


def load_inbox():
    if not INBOX.exists():
        return []
    try:
        return json.loads(INBOX.read_text(encoding="utf-8"))
    except Exception:
        return []


def append_command(agent_id: str, text: str):
    rows = load_inbox()
    rows.insert(0, {
        "id": uuid.uuid4().hex[:8],
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "text": text,
        "target": "auto",
        "routed_to": agent_id,
        "agent_id": agent_id,
        "sends": False,
        "status": "queued",
        "note": "fleet pulse (recurring alter job)",
        "via": "fleet-pulse",
    })
    rows = rows[:300]
    INBOX.write_text(json.dumps(rows, indent=2), encoding="utf-8")


def trigger_dispatch():
    # data=b'' forces POST (urlopen defaults to GET; dispatch only handles /dispatch as POST)
    try:
        urllib.request.urlopen("http://127.0.0.1:8912/dispatch", data=b"", timeout=5)
    except Exception:
        pass


def pulse_once():
    for agent_id, (job, _) in ALTER_JOBS.items():
        append_command(agent_id, f"[pulse] {job}")
    trigger_dispatch()


def loop():
    # prime immediately, then on interval
    while True:
        try:
            pulse_once()
        except Exception:
            pass
        time.sleep(ALTER_INTERVAL)


class H(BaseHTTPRequestHandler):
    def _json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.split("?")[0].rstrip("/") == "/health":
            self._json({"ok": True, "alters": len(ALTER_JOBS), "interval": ALTER_INTERVAL})
        else:
            self.send_response(404); self.end_headers()

    def log_message(self, *a):
        pass


def main():
    threading.Thread(target=loop, daemon=True).start()
    print(f"Fleet Pulse on :{PORT} — {len(ALTER_JOBS)} alters, every {ALTER_INTERVAL}s")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()


if __name__ == "__main__":
    main()
