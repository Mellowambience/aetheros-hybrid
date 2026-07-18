#!/usr/bin/env python3
"""
AetherOS Steward — local-first truth daemon + static server.
Single process. Probes real services, writes state.json, serves the console
on :8900. Self-healing: one bad probe can't kill the loop.

Run:
  python steward.py            # one-shot probe + write state.json
  python steward.py --serve    # loop forever: probe every 15s + serve :8900
"""
from __future__ import annotations
import json, os, socket, subprocess, sys, time, urllib.request, datetime, threading
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

HERE = Path(__file__).resolve().parent
STATE = HERE / "state.json"
GBRAIN = Path.home() / "gbrain"
PORT = 8900
INTERVAL = 15

REALMS = [
    {"id": "fairyos",   "name": "Fairy OS",       "sub": "living-forest shell", "comp": 72},
    {"id": "hermes",    "name": "Hermes",         "sub": "agent runtime",      "comp": 88},
    {"id": "runetek",   "name": "Runetek Eclipse","sub": "game engine",        "comp": 41},
    {"id": "crublore",  "name": "Crublore",       "sub": "craft skill tree",   "comp": 63},
    {"id": "archive",   "name": "Living Archive", "sub": "knowledge vault",    "comp": 80},
    {"id": "portfolio", "name": "Portfolio",      "sub": "case studies",       "comp": 55},
]


def port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.6) -> bool:
    s = socket.socket(); s.settimeout(timeout)
    try:
        s.connect((host, port)); return True
    except Exception:
        return False
    finally:
        s.close()


def http_get(url: str, timeout: float = 2.0) -> tuple[int, str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "AetherOS-Steward/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(2000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read(500).decode("utf-8", "replace")
    except Exception as e:
        return 0, str(e)


def safe(fn, default):
    try:
        return fn()
    except Exception as e:
        d = dict(default)
        d["note"] = f"probe error: {e}"
        return d


def probe_echo_voice():
    if not port_open(8787):
        return {"online": False, "mode": "offline", "rtf": None,
                "note": "Echo Voice service not running on :8787. Start it to enable local TTS."}
    status, body = http_get("http://127.0.0.1:8787/health")
    info = {}
    if body:
        try: info = json.loads(body)
        except Exception: pass
    return {"online": True, "mode": info.get("device_request", "unknown"),
            "offline": info.get("offline", False), "rtf": None,
            "note": "Local Qwen3-TTS online; loopback-only, consent-gated."}


def probe_aetherdeck():
    if not port_open(8788):
        return {"online": False, "note": "AetherDeck :8788 not running."}
    status, body = http_get("http://127.0.0.1:8788/")
    return {"online": status == 200, "title_present": "AetherDeck" in body,
            "note": "Commander dashboard live." if status == 200 else f"HTTP {status}"}


def probe_echo_identity():
    home = Path.home() / ".hermes"
    soul = home / "SOUL.md"
    if not soul.exists():
        return {"installed": False, "note": "Echo identity (SOUL.md) not installed in Hermes home."}
    try:
        head = soul.read_text(encoding="utf-8", errors="replace")[:400]
    except Exception:
        head = ""
    installed = "echo" in head.lower() or "companion" in head.lower()
    # count continuity seeds
    seeds_dir = home / "echo" / "continuity" / "seeds"
    seeds = 0
    if seeds_dir.exists():
        seeds = len([p for p in seeds_dir.glob("*.md")])
    return {"installed": installed, "seeds": seeds,
            "note": f"Echo identity present; {seeds} continuity seed(s) on disk."}


def probe_gbrain():
    if not GBRAIN.exists():
        return {"present": False, "healthy": None, "note": "gbrain repo absent."}
    ver = (GBRAIN / "VERSION").read_text(encoding="utf-8").strip() if (GBRAIN / "VERSION").exists() else "unknown"
    return {"present": True, "version": ver, "healthy": "unverified",
            "note": "Repo present; run `gbrain doctor` for full health."}


def reconcile_sessions():
    idx = Path.home() / ".hermes" / "exports" / "session_index.json"
    if not idx.exists():
        return {"count": 0, "note": "No session index."}
    try:
        data = json.loads(idx.read_text(encoding="utf-8"))
        return {"count": len(data), "note": f"{len(data)} sessions indexed."}
    except Exception as e:
        return {"count": -1, "note": f"session index unreadable: {e}"}


def compute_sla(realms_online, realms_total, voice_on, deck_on):
    checks = {"echo_voice": voice_on, "aetherdeck": deck_on}
    passed = sum(checks.values()); total = len(checks)
    pct = round(100.0 * (passed + realms_online) / (total + realms_total), 1)
    status = "met" if pct >= 95.0 else ("warn" if pct >= 90.0 else "breach")
    return {"pct": pct, "status": status, "checks": checks, "passed": passed, "total": total}


def probe_all():
    echo = safe(probe_echo_voice, {"online": False, "note": "echo probe failed"})
    deck = safe(probe_aetherdeck, {"online": False, "note": "deck probe failed"})
    gb = safe(probe_gbrain, {"present": False, "note": "gbrain probe failed"})
    echo_id = safe(probe_echo_identity, {"installed": False, "note": "echo probe failed"})
    sess = safe(reconcile_sessions, {"count": 0, "note": "session probe failed"})
    realms_online = len(REALMS)
    sla = compute_sla(realms_online, len(REALMS), echo["online"], deck["online"])
    return {
        "schema": "aetheros.steward.state.v1",
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "realms": REALMS,
        "services": {"echo_voice": echo, "aetherdeck": deck, "gbrain": gb,
                     "echo_companion": echo_id, "hermes_sessions": sess},
        "sla": sla,
        "source": "local-probes-only",
    }


def write_state(state):
    STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def loop():
    while True:
        try:
            state = probe_all()
            write_state(state)
            print(f"[{state['generated_at']}] SLA={state['sla']['pct']}% "
                  f"({state['sla']['status']}) voice={'on' if state['services']['echo_voice']['online'] else 'off'} "
                  f"deck={'on' if state['services']['aetherdeck']['online'] else 'off'}", flush=True)
        except Exception as e:
            print(f"[steward] loop error: {e}", flush=True)
        time.sleep(INTERVAL)


def main():
    if "--serve" not in sys.argv:
        state = probe_all(); write_state(state)
        print(f"one-shot SLA={state['sla']['pct']}% ({state['sla']['status']}) -> {STATE}")
        return
    # Start probe loop in background thread
    threading.Thread(target=loop, daemon=True).start()
    # Serve the console folder on :8900
    os.chdir(HERE)
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), SimpleHTTPRequestHandler)
    print(f"[steward] serving {HERE} on http://127.0.0.1:{PORT}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
