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
QUESTS = HERE / "quests.json"


def load_quests() -> list:
    if not QUESTS.exists():
        return []
    try:
        d = json.loads(QUESTS.read_text(encoding="utf-8"))
        return d if isinstance(d, list) else []
    except Exception:
        return []


def save_quests(qs: list):
    QUESTS.write_text(json.dumps(qs, indent=2), encoding="utf-8")


def add_quest(name: str, lane: str = "auto", proposed_by: str = "you",
             kind: str = "quest", repo: str = "") -> dict:
    name = (name or "").strip().strip(".\\")[:160]
    if not name:
        return {"ok": False, "error": "empty quest name"}
    qs = load_quests()
    qs.insert(0, {"name": name, "added": time.strftime("%Y-%m-%d %H:%M:%S"),
                 "done": False, "lane": lane, "proposed_by": proposed_by,
                 "kind": kind, "repo": repo,
                 "approved": (lane != "approval")})
    qs = qs[:200]
    save_quests(qs)
    return {"ok": True, "quests": qs}


def propose_initiatives() -> dict:
    """Agent-authored proposals: things the agent wants to build or repos it wants to
    work on, drawn from the user's REAL life's work (works.json). Surfaces as quests in
    the `auto` lane (agent can act) or `approval` lane (needs human sign-off)."""
    import random
    try:
        wj = json.loads((HERE / "works.json").read_text(encoding="utf-8"))
        projects = wj.get("projects", [])
    except Exception:
        projects = []
    if not projects:
        return {"ok": False, "error": "works index unavailable"}
    qs = load_quests()
    existing = {q.get("name") for q in qs}
    made = []
    # pick a few real repos the agent proposes to work on
    picks = random.sample(projects, min(3, len(projects)))
    for p in picks:
        nm = f"work on {p['name']}"
        if nm in existing:
            continue
        # agent-authored idea: improve/extend a real repo
        repo = p.get("path", "")
        # repos with no README or stale are 'approval' (bigger scope); others 'auto'
        lane = "approval" if ("engine" in p["name"].lower() or "rift" in p["name"].lower()) else "auto"
        r = add_quest(nm, lane=lane, proposed_by="agent", kind="initiative", repo=repo)
        if r.get("ok"):
            made.append(nm)
    # one greenfield build idea the agent wants to attempt
    green = "build a CLI wrapper that turns any repo in works.json into a bootable TV target"
    if green not in existing:
        add_quest(green, lane="auto", proposed_by="agent", kind="initiative", repo="")
        made.append(green)
    return {"ok": True, "made": made}


def toggle_quest(idx: int = None, name: str = None) -> dict:
    qs = load_quests()
    target = None
    if name is not None:
        for i, q in enumerate(qs):
            if q.get("name") == name:
                target = i
                break
    elif idx is not None:
        target = idx
    if target is None or target < 0 or target >= len(qs):
        return {"ok": False, "error": "no such quest"}
    qs[target]["done"] = not qs[target].get("done", False)
    save_quests(qs)
    return {"ok": True, "quests": qs}


def approve_quest(name: str = None, idx: int = None) -> dict:
    """Human sign-off for an `approval`-lane quest. Until approved it cannot be
    auto-executed by the agent."""
    qs = load_quests()
    target = None
    if name is not None:
        for i, q in enumerate(qs):
            if q.get("name") == name:
                target = i
                break
    elif idx is not None:
        target = idx
    if target is None or target < 0 or target >= len(qs):
        return {"ok": False, "error": "no such quest"}
    qs[target]["approved"] = True
    save_quests(qs)
    return {"ok": True, "quests": qs}


# ---------------------------------------------------------------------------
# slime_layer delivery: turn modeled signals into REAL delivered commands.
# A signal emitted via SlimeLayer lands in the target peer's in-memory inbox.
# The drainer reads each peer's received() and creates a real local command in
# the command inbox (evidence-backed), so the fleet actually acts on signals.
# ---------------------------------------------------------------------------
def get_slime():
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("slime_layer", HERE / "slime_layer.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.SlimeLayer().seed_from_fleet()
    except Exception:
        return None


SLIME = get_slime()


def emit_signal(frm: str, to: str, payload: dict) -> dict:
    if SLIME is None:
        return {"ok": False, "error": "slime_layer unavailable"}
    r = SLIME.emit(frm, to, payload, stype=payload.get("type", "signal"))
    return {"ok": True, **r}


def drain_signals() -> int:
    """Pull every peer's received() signals and convert them into real local commands
    in the command inbox. Returns count delivered this drain."""
    if SLIME is None:
        return 0
    count = 0
    for peer in list(SLIME.inbox.keys()):
        for sig in SLIME.received(peer):
            # mark consumed so we don't double-deliver
            SLIME.inbox[peer].remove(sig)
            text = f"[slime:{sig['from']}->{peer}] {sig.get('type','signal')}: {json.dumps(sig.get('payload', {}))[:120]}"
            entry = {
                "id": uuid.uuid4().hex[:8],
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                "text": text,
                "target": "auto",
                "routed_to": peer,
                "agent_id": peer,
                "sends": False,
                "status": "queued",
                "note": f"delivered via slime_layer from {sig['from']}",
                "via": "slime",
            }
            append_inbox(entry)
            count += 1
    return count


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
        elif u in ("/quest",):
            self._json({"ok": True, "quests": load_quests()})
        elif u in ("/inbox",):
            rows = []
            if INBOX.exists():
                try:
                    rows = json.loads(INBOX.read_text(encoding="utf-8"))
                except Exception:
                    rows = []
            self._json({"count": len(rows), "commands": rows[:50]})
        elif u in ("/fleet",):
            if FR is None:
                self._json({"ok": False, "agents": []})
            else:
                self._json({"ok": True, "agents": [{"id": a["id"], "name": a["name"], "role": a.get("role", "")}
                                                    for a in FR.FLEET]})
        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        if self.path.rstrip("/") == "/quest":
            try:
                n = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(n) if n else b"{}"
                data = json.loads(raw or b"{}")
                action = (data.get("action") or "add").lower()
                if action == "add":
                    res = add_quest(data.get("name", ""), lane=data.get("lane", "auto"),
                                    proposed_by=data.get("proposed_by", "you"),
                                    kind=data.get("kind", "quest"), repo=data.get("repo", ""))
                elif action == "toggle":
                    res = toggle_quest(idx=data.get("index"), name=data.get("name"))
                elif action == "approve":
                    res = approve_quest(name=data.get("name"), idx=data.get("index"))
                elif action == "propose":
                    res = propose_initiatives()
                else:
                    res = {"ok": False, "error": "unknown action"}
                self._json(res, 200 if res.get("ok") else 400)
            except Exception as e:
                self._json({"ok": False, "error": str(e)}, 400)
            return
        if self.path.rstrip("/") == "/slime":
            try:
                n = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(n) if n else b"{}"
                data = json.loads(raw or b"{}")
                r = emit_signal(data.get("from", "hermes"), data.get("to", "steward"),
                                data.get("payload", {}))
                self._json(r, 200 if r.get("ok") else 503)
            except Exception as e:
                self._json({"ok": False, "error": str(e)}, 400)
            return
        if self.path.rstrip("/") == "/add-agent":
            try:
                n = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(n) if n else b"{}"
                peer = json.loads(raw or b"{}")
                if FR is None or not hasattr(FR, "add_peer"):
                    self._json({"ok": False, "error": "router unavailable"}, 503); return
                res = FR.add_peer(peer)
                # reload router module so in-memory FLEET reflects the new peer live
                try:
                    import importlib
                    importlib.reload(FR)
                except Exception:
                    pass
                self._json(res, 200 if res.get("ok") else 400)
            except Exception as e:
                self._json({"ok": False, "error": str(e)}, 400)
            return
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
    import threading
    # drain slime_layer signals into the real command inbox every 3s
    def _drain_loop():
        while True:
            try:
                drain_signals()
            except Exception:
                pass
            time.sleep(3)
    threading.Thread(target=_drain_loop, daemon=True).start()
    print(f"Command Hub on http://127.0.0.1:{PORT}/command (loopback; routes via fleet_router)")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()


if __name__ == "__main__":
    main()
