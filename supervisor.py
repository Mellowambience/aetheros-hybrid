#!/usr/bin/env python3
"""
AetherOS Supervisor — keeps the local web app alive across turns/sessions.
Runs the console HTTP server, the steward probe loop, and the voice launcher
endpoint as managed child processes. If any dies, it restarts it.

Loopback-only. No cloud. Local-first by construction.

Run:  python supervisor.py            # foreground (or background=true)
      python supervisor.py --once      # start children once, then exit
"""
from __future__ import annotations
import subprocess, sys, time, os
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY = sys.executable


def spawn(cmd: list[str], name: str) -> subprocess.Popen:
    p = subprocess.Popen(cmd, cwd=str(HERE),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"[supervisor] started {name} pid={p.pid}")
    return p


def main():
    children = {}

    # 1) console server on :8900
    children["server"] = spawn([PY, "-m", "http.server", "8900"], "console-server")
    # 2) steward loop (writes state.json every 15s)
    children["steward"] = spawn([PY, "steward.py", "--serve"], "steward")
    # 3) voice launcher endpoint on :8910
    children["launcher"] = spawn([PY, "launcher.py"], "voice-launcher")
    # 5) mothership thinking API on :8920
    children["mothership"] = spawn([PY, "mothership.py"], "mothership")
    # 6) credit monitor (watches zyloo/tokenrouter for usable balance)
    children["credit"] = spawn([PY, "credit_monitor.py", "--interval", "120"], "credit-monitor")
    # 7) command hub — bubble dock brain (routes user commands to fleet)
    children["hub"] = spawn([PY, "command_hub.py"], "command-hub")
    # 8) dispatch — executes T0/T1 locally, queues T2 to Outbox
    children["dispatch"] = spawn([PY, "dispatch.py"], "dispatch")
    # 9) system map — live blueprint telemetry
    children["sysmap"] = spawn([PY, "system_map.py"], "system-map")

    if "--once" in sys.argv:
        print("[supervisor] --once: children launched; exiting.")
        return

    print("[supervisor] watching children; Ctrl+C to stop.")
    try:
        while True:
            time.sleep(5)
            for name, proc in list(children.items()):
                if proc.poll() is not None:
                    print(f"[supervisor] {name} exited ({proc.returncode}); restarting…")
                    if name == "server":
                        children[name] = spawn([PY, "-m", "http.server", "8900"], name)
                    elif name == "steward":
                        children[name] = spawn([PY, "steward.py", "--serve"], name)
                    elif name == "voice":
                        children[name] = spawn([PY, "voice", "voice_loop.py"], name)
                    elif name == "mothership":
                        children[name] = spawn([PY, "mothership.py"], name)
                    elif name == "credit":
                        children[name] = spawn([PY, "credit_monitor.py", "--interval", "120"], name)
                    elif name == "hub":
                        children[name] = spawn([PY, "command_hub.py"], name)
                    elif name == "dispatch":
                        children[name] = spawn([PY, "dispatch.py"], name)
                    elif name == "sysmap":
                        children[name] = spawn([PY, "system_map.py"], name)
                    else:
                        children[name] = spawn([PY, "launcher.py"], name)
    except KeyboardInterrupt:
        print("[supervisor] stopping children…")
        for p in children.values():
            try:
                p.terminate()
            except Exception:
                pass


if __name__ == "__main__":
    main()
