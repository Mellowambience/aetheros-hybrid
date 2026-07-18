#!/usr/bin/env python3
"""
AetherOS Hybrid — run everything from one entry point.

Starts the supervisor (which brings up the web app + all fleet services
on loopback) and prints the local URL. Ctrl+C stops everything.

Usage:
    python run.py            # foreground, logs to console
    python run.py --bg       # detach-ish (still attached, but clears screen)
"""
from __future__ import annotations
import subprocess, sys, time, os
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY = sys.executable


def main():
    print("AetherOS Hybrid — starting supervisor (local-first, loopback)…")
    proc = subprocess.Popen([PY, "supervisor.py"], cwd=str(HERE))
    time.sleep(3)
    # verify the app came up
    import urllib.request
    ok = False
    for _ in range(10):
        try:
            urllib.request.urlopen("http://127.0.0.1:8900/aetherhaven_desktop.html", timeout=2)
            ok = True
            break
        except Exception:
            time.sleep(1)
    if ok:
        print("\n  ✅ Pocket Realm is live:\n     http://127.0.0.1:8900/aetherhaven_desktop.html\n")
        print("  (Ctrl+C to stop the whole fleet)\n")
    else:
        print("  ⚠ supervisor started but :8900 not responding yet — check console output above.")
    try:
        proc.wait()
    except KeyboardInterrupt:
        print("\n[run] stopping supervisor + children…")
        proc.terminate()


if __name__ == "__main__":
    main()
