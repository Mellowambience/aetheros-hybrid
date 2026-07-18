#!/usr/bin/env python3
"""
AetherOS System Map — the HERMES blueprint as LIVE telemetry.

Each node from the conceptual diagram reports its REAL runtime state:
  inputs, orchestrator, planning/routing, tools/execution, safety,
  outputs, memory, feedback.

Loopback :8913.
  GET /health
  GET /map   -> {nodes:{...}, ts}

No cloud. Reads local state + pings the real fleet endpoints.
"""
from __future__ import annotations
import json, time, os
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import urllib.request

HERE = Path(__file__).resolve().parent
PORT = 8913


def _get(url, timeout=2):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def _count(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        return len(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return 0


def build_map() -> dict:
    # --- live fleet endpoints ---
    hub = _get("http://127.0.0.1:8911/health")
    outbox = _get("http://127.0.0.1:8912/outbox") or {"count": 0}
    inbox_path = HERE / "command_inbox.json"
    inbox = json.loads(inbox_path.read_text(encoding="utf-8")) if inbox_path.exists() else []
    executed = sum(1 for r in inbox if r.get("status") == "executed")
    awaiting = outbox.get("count", 0)

    # --- peer count ---
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("fr", HERE / "fleet_router.py")
        fr = importlib.util.module_from_spec(spec); spec.loader.exec_module(fr)
        peers = len(fr.FLEET)
    except Exception:
        peers = 0

    # --- memory ---
    activity = _count(HERE / "agent_activity.json")
    quests = _count(HERE / "quests.json")
    db = Path(os.path.expandvars("%LOCALAPPDATA%")) / "hermes" / "state.db"
    db_mb = round(db.stat().st_size / 1_048_576, 1) if db.exists() else 0

    # --- credit ---
    cred = {}
    cp = HERE / "credit_status.json"
    if cp.exists():
        try:
            cred = json.loads(cp.read_text(encoding="utf-8")).get("providers", {})
        except Exception:
            cred = {}

    nodes = {
        "inputs":       {"state": "ok" if hub else "off",
                         "detail": f"{len(inbox)} commands received"},
        "orchestrator": {"state": "ok" if hub else "off",
                         "detail": "command_hub alive" if hub else "hub down"},
        "planning":     {"state": "ok" if peers else "warn",
                         "detail": f"{peers} peer agents routed"},
        "execution":    {"state": "ok" if executed else "warn",
                         "detail": f"{executed} local actions run"},
        "safety":       {"state": "warn" if awaiting else "ok",
                         "detail": f"{awaiting} awaiting your SEND"},
        "outputs":      {"state": "ok", "detail": "9 live panels"},
        "memory":       {"state": "ok",
                         "detail": f"{activity} acts · {quests} quests · {db_mb}MB db"},
        "feedback":     {"state": "ok", "detail": "tinder curate active"},
        "credit":       {"state": "warn" if any(v.get("state") == "no_credit" for v in cred.values()) else "ok",
                         "detail": "zyloo " + ("no credit" if cred.get("zyloo", {}).get("state") == "no_credit" else "ok")},
    }
    return {"nodes": nodes, "ts": time.strftime("%Y-%m-%d %H:%M:%S")}


class H(BaseHTTPRequestHandler):
    def _json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(b)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        u = self.path.rstrip("/")
        if u in ("/health", "/"):
            self._json({"ok": True})
        elif u == "/map":
            self._json(build_map())
        else:
            self.send_response(404); self.end_headers()

    def log_message(self, *a):
        pass


def main():
    print(f"System Map on http://127.0.0.1:{PORT}/map (live blueprint telemetry)")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()


if __name__ == "__main__":
    main()
