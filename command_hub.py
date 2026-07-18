#!/usr/bin/env python3
"""
AetherOS Command Hub — the brain behind the Pocket Realm bubble dock.

Receives a natural-language command from the user (typed in the bubble dock),
routes it to the correct fleet peer via fleet_router, logs it to a local
inbox (auditable, human-gated), and returns the routing decision.

It does NOT auto-execute external/high-impact actions. Those are flagged
`sends:true` and require the user's explicit SEND in the UI. This is the
human gate from the AetherOS design: the fleet may *plan/observe*, but
external execution waits for you.

Endpoints (loopback :8911):
  POST /command   {"text":"...","target":"agent_id|auto"}
                  -> {"routed_to":..., "agent":..., "sends":bool,
                      "note":..., "id":..., "ts":...}
  GET  /inbox     -> list of recent commands (audit trail)
  GET  /health    -> {"ok":true}

No cloud. No key. Local-first by construction.
"""
from __future__ import annotations
import json, os, time, uuid
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = Path(__file__).resolve().parent
PORT = 8911
INBOX = HERE / "command_inbox.json"

# actions that need the human SEND gate (external / high-impact)
EXTERNAL_KEYWORDS = ["send ", "post ", "deploy", "publish", "email", "tweet", "x.com",
                     "buy ", "purchase", "top up", "topup", "payment", "cash app",
                     "launch externally", "expose", "open port", " dm ", "dm me"]


def load_fleet_router():
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("fleet_router", HERE / "fleet_router.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception as e:
        return None


FR = load_fleet_router()
if FR is None:
    print("[WARN] fleet_router.py failed to load — commands will default to Hermes runtime.")


def route(text: str, target: str = "auto") -> dict:
    if FR is None:
        return {"agent": "hermes", "role": "Runtime", "sends": False,
                "note": "fleet_router unavailable — defaulting to Hermes runtime."}
    if target and target != "auto":
        for a in FR.FLEET:
            if a["id"] == target:
                return {"agent": a["name"], "id": a["id"], "role": a["role"],
                        "sends": _needs_send(text),
                        "note": f"Routed by explicit target → {a['name']} ({a['role']})."}
        return {"agent": "hermes", "role": "Runtime", "sends": _needs_send(text),
                "note": f"Unknown target '{target}' — defaulted to Hermes."}
    r = FR.route(text)
    return {"agent": r.get("owner_name"), "id": r.get("owner"), "role": "",
            "sends": _needs_send(text), "note": r.get("note", "")}


def _needs_send(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in EXTERNAL_KEYWORDS)


def append_inbox(entry: dict):
    rows = []
    if INBOX.exists():
        try:
            rows = json.loads(INBOX.read_text(encoding="utf-8"))
        except Exception:
            rows = []
    rows.insert(0, entry)
    rows = rows[:200]
    INBOX.write_text(json.dumps(rows, indent=2), encoding="utf-8")


class H(BaseHTTPRequestHandler):
    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        u = self.path.rstrip("/")
        if u in ("/health",):
            self._json({"ok": True})
        elif u in ("/inbox",):
            rows = []
            if INBOX.exists():
                try:
                    rows = json.loads(INBOX.read_text(encoding="utf-8"))
                except Exception:
                    rows = []
            self._json({"count": len(rows), "commands": rows[:50]})
        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        if self.path.rstrip("/") != "/command":
            self.send_response(404); self.end_headers(); return
        try:
            n = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(n) if n else b"{}"
            data = json.loads(raw or b"{}")
        except Exception as e:
            self._json({"error": str(e)}, 400); return
        text = (data.get("text") or "").strip()
        target = data.get("target", "auto") or "auto"
        if not text:
            self._json({"error": "empty command"}, 400); return
        r = route(text, target)
        entry = {
            "id": uuid.uuid4().hex[:8],
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "text": text,
            "target": target,
            "routed_to": r.get("agent"),
            "agent_id": r.get("id"),
            "sends": r["sends"],
            "status": "pending_send" if r["sends"] else "queued",
            "note": r.get("note", ""),
        }
        append_inbox(entry)
        # T0/T1 commands auto-execute locally via dispatch; T2 waits for SEND.
        if not r["sends"]:
            try:
                import urllib.request
                urllib.request.urlopen("http://127.0.0.1:8912/dispatch", timeout=3)
            except Exception:
                pass  # dispatch not up yet — will run on next tick
        self._json(entry, 200)

    def log_message(self, *a):
        pass


def main():
    print(f"Command Hub on http://127.0.0.1:{PORT}/command (loopback; routes via fleet_router)")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()


if __name__ == "__main__":
    main()
