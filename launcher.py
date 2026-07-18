#!/usr/bin/env python3
"""
AetherOS Voice Launcher — attempts to bring the local Echo Voice service (:8787)
online on demand. Honest: it only launches if the package is installed and
dependencies are present. It never fakes success.

Endpoint consumed by aetheros_hybrid.html -> ./launch_voice.json

Run as a tiny local API:
    python launcher.py            # serves POST /launch on :8910 (loopback)
Or import launch() to call directly from steward.
"""
from __future__ import annotations
import json, os, subprocess, sys, threading, time, urllib.request
from pathlib import Path

HOME = Path.home()
PKG = HOME / "echo_voice_extract" / "echo_voice_qwen_integration"
VOICE_PORT = 8787
LAUNCHER_PORT = 8910


def _port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.4) -> bool:
    import socket
    s = socket.socket(); s.settimeout(timeout)
    try:
        s.connect((host, port)); return True
    except Exception:
        return False
    finally:
        s.close()


def launch() -> dict:
    """Try to start Echo Voice. Returns a status dict the UI can show."""
    if _port_open(VOICE_PORT):
        return {"launched": True, "message": "Echo Voice already running on :8787."}

    run_ps = PKG / "scripts" / "run_windows.ps1"
    main_py = PKG / "src" / "echo_voice" / "main.py"
    venv = PKG / ".venv" / "Scripts" / "python.exe"

    if not PKG.exists():
        return {"launched": False, "message": "Echo Voice package not found at " + str(PKG)}
    if not (run_ps.exists() or main_py.exists()):
        return {"launched": False, "message": "Echo Voice entrypoint missing; package incomplete."}
    if not venv.exists():
        return {"launched": False,
                "message": "No .venv — run bootstrap_windows.ps1 first (installs qwen-tts + PyTorch). Voice stays dormant by design."}

    # Launch headless in background; do NOT block the UI.
    try:
        if run_ps.exists():
            subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                              "-File", str(run_ps)], cwd=str(PKG),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.Popen([str(venv), str(main_py)], cwd=str(PKG),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        return {"launched": False, "message": f"Launch failed: {e}"}

    return {"launched": True, "message": "Launching Echo Voice (model download may take minutes on first run). Polling…"}


def _serve_once():
    """Minimal loopback HTTP so the HTML can POST ./launch_voice.json semantics."""
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path.rstrip("/") in ("/launch", "/launch_voice.json"):
                res = launch()
                body = json.dumps(res).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404); self.end_headers()

        def log_message(self, *a):  # silence
            pass

    srv = HTTPServer(("127.0.0.1", LAUNCHER_PORT), H)
    srv.serve_forever()


def main():
    if "--launch" in sys.argv:
        print(json.dumps(launch(), indent=2))
        return
    print(f"Voice launcher on http://127.0.0.1:{LAUNCHER_PORT}/launch (loopback)")
    _serve_once()


if __name__ == "__main__":
    main()
