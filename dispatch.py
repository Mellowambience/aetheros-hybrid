#!/usr/bin/env python3
"""
AetherOS Dispatch — consumes command_inbox.json and executes local (T0/T1) commands,
leaving external (T2) commands in `awaiting_send` for the human SEND.

Loopback :8912.
  GET  /health
  GET  /outbox          -> list of T2 (awaiting_send) commands
  POST /dispatch        -> process pending T0/T1 commands now (idempotent)
  POST /send/{id}       -> human-approved external execution marker (records approval;
                          real external calls still require the integration + key in .env)
  GET  /activity        -> recent agent_activity.json

Design: T0/T1 (no sends:true) auto-execute locally via agents.handlers.
        T2 (sends:true) never auto-execute — they wait for /send/{id}.
"""
from __future__ import annotations
import json, time, uuid
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = Path(__file__).resolve().parent
PORT = 8912
INBOX = HERE / "command_inbox.json"

import importlib.util
_spec = importlib.util.spec_from_file_location("handlers", HERE / "agents" / "handlers.py")
H = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(H)


def load_inbox():
    if not INBOX.exists():
        return []
    try:
        return json.loads(INBOX.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_inbox(rows):
    INBOX.write_text(json.dumps(rows, indent=2), encoding="utf-8")


def process_pending() -> dict:
    rows = load_inbox()
    done, skipped = 0, 0
    for r in rows:
        if r.get("status") == "queued":
            res = H.handle(r.get("agent_id") or "hermes", r.get("text", ""),
                           repo=r.get("repo", ""))
            r["status"] = "executed" if res.get("ok") else "error"
            r["exec_detail"] = res.get("detail", "")
            r["executed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            done += 1
        elif r.get("status") in ("pending_send", "awaiting_send"):
            skipped += 1  # T2 — waits for human SEND
    save_inbox(rows)
    return {"processed": done, "awaiting_send": skipped,
            "ts": time.strftime("%Y-%m-%d %H:%M:%S")}


def approve_send(cid: str) -> dict:
    rows = load_inbox()
    for r in rows:
        if r.get("id") == cid and r.get("sends"):
            r["status"] = "approved_send"
            r["approved_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            save_inbox(rows)
            return {"ok": True, "id": cid,
                    "note": "approved — external execution authorized by owner. "
                            "Real API call fires only if the integration + key exist in .env."}
    return {"ok": False, "id": cid, "note": "not found or not an external (sends) command"}


class H_(BaseHTTPRequestHandler):
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
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        u = self.path.split("?")[0].rstrip("/")
        if u == "/health":
            self._json({"ok": True})
        elif u == "/outbox":
            rows = [r for r in load_inbox() if r.get("sends")]
            self._json({"count": len(rows), "commands": rows[:50]})
        elif u == "/activity":
            p = HERE / "agent_activity.json"
            self._json({"activity": json.loads(p.read_text(encoding="utf-8")) if p.exists() else []})
        elif u == "/snapshot":
            # real pipeline state — drives the Orchestrator view + RTS enemies
            rows = load_inbox()
            pending, awaiting, done = [], [], []
            for r in rows:
                st = r.get("status")
                rec = {"id": r.get("id"), "text": r.get("text", ""),
                       "agent": r.get("agent_id", "hermes"), "status": st}
                if st == "queued":
                    pending.append(rec)
                elif st in ("pending_send", "awaiting_send"):
                    awaiting.append(rec)
                elif st in ("executed", "approved_send", "error"):
                    rec["executed_at"] = r.get("executed_at", "")
                    done.append(rec)
            # credit state (real)
            cred = {}
            cp = HERE / "credit_status.json"
            if cp.exists():
                try:
                    cred = json.loads(cp.read_text(encoding="utf-8"))
                except Exception:
                    cred = {}
            self._json({
                "pending": pending, "awaiting": awaiting, "done": done,
                "counts": {"pending": len(pending), "awaiting": len(awaiting),
                           "done": len(done), "total": len(rows)},
                "credit": cred,
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            })
        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        u = self.path.rstrip("/")
        if u == "/dispatch":
            self._json(process_pending())
        elif u.startswith("/send/"):
            cid = u.split("/send/", 1)[1]
            self._json(approve_send(cid))
        else:
            self.send_response(404); self.end_headers()

    def log_message(self, *a):
        pass


def main():
    print(f"Dispatch on http://127.0.0.1:{PORT} (T0/T1 auto-exec, T2 awaits SEND)")
    ThreadingHTTPServer(("127.0.0.1", PORT), H_).serve_forever()


if __name__ == "__main__":
    main()
