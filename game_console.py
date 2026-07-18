#!/usr/bin/env python3
"""game_console.py — the bootable game console host (port 8914).

Local-first. Boots/stops REAL processes so the user can watch agents play incubated
games on the TV and catch bugs fast. Manages:
  - game   : built-in incubated canvas game (tv_game.html), served here
  - console: Becoming-Console (the daily-room OS) local server
  - tv     : agent-tv broadcast hub server
Each boot is a real subprocess tracked by pid; stop kills it. No cloud.
"""
import http.server, json, os, subprocess, sys, threading, time
from http.server import SimpleHTTPRequestHandler

HOST = "127.0.0.1"
PORT = 8914
ROOT = os.path.dirname(os.path.abspath(__file__))
HOME = "C:/Users/nator"

# real, inspectable boot entries. command is a real subprocess.
TARGETS = {
    "game": {
        "name": "Incubated Game",
        "desc": "Self-contained agent-played canvas game with live debug stream.",
        "serve": "/game",          # served by this process (no subprocess needed)
        "cmd": None,
    },
    "console": {
        "name": "Becoming Console",
        "desc": "The bootable daily-room OS (host for incubated games).",
        "serve": "http://127.0.0.1:8746/",
        "cmd": [sys.executable, os.path.join(HOME, "Becoming-Console", "server.py"), "--port", "8746"],
    },
    "tv": {
        "name": "Agent TV",
        "desc": "Live broadcast hub aggregating local feeds.",
        "serve": "http://127.0.0.1:8901/",
        "cmd": [sys.executable, "-m", "http.server", "8901", "--bind", "127.0.0.1", "--directory",
                os.path.join(HOME, "agent-tv")],
    },
}

PROC = {}  # key -> subprocess.Popen


def boot(key):
    t = TARGETS.get(key)
    if not t:
        return {"ok": False, "error": "unknown target"}
    if key in PROC and PROC[key].poll() is None:
        return {"ok": True, "running": True, "pid": PROC[key].pid, "serve": t["serve"]}
    if t["cmd"] is None:
        # served in-process
        PROC[key] = None  # sentinel: alive, no pid
        return {"ok": True, "running": True, "pid": None, "serve": t["serve"], "inprocess": True}
    try:
        p = subprocess.Popen(t["cmd"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=0x00000200)  # CREATE_NO_WINDOW
        PROC[key] = p
        # give it a moment, then confirm it is alive
        time.sleep(1.2)
        if p.poll() is None:
            return {"ok": True, "running": True, "pid": p.pid, "serve": t["serve"]}
        return {"ok": False, "error": "process exited on boot (code %s)" % p.returncode}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def stop(key):
    t = TARGETS.get(key)
    if not t:
        return {"ok": False, "error": "unknown target"}
    p = PROC.pop(key, None)
    if p is None:
        return {"ok": True, "running": False, "note": "not running"}
    try:
        # kill the whole process tree (Python -m http.server spawns a child
        # that survives a plain terminate). Windows: taskkill /T. POSIX: killpg.
        if sys.platform.startswith("win"):
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            import os, signal
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGKILL)
            except Exception:
                p.kill()
        # ensure tracked handle is reaped
        try:
            p.wait(timeout=3)
        except Exception:
            pass
        return {"ok": True, "running": False, "stopped": key}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def status():
    out = []
    for k, t in TARGETS.items():
        p = PROC.get(k)
        alive = (p is not None and p.poll() is None) or (t["cmd"] is None and k in PROC)
        out.append({"key": k, "name": t["name"], "desc": t["desc"], "serve": t["serve"],
                    "running": bool(alive), "pid": p.pid if (p and alive) else None})
    return out


class H(SimpleHTTPRequestHandler):
    def _j(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = self.path.split("?")[0].rstrip("/")
        if u in ("", "/health"):
            return self._j({"ok": True, "console": [t["name"] for t in TARGETS.values()]})
        if u == "/list":
            return self._j({"targets": status()})
        if u == "/game" or u == "/game/":
            return self.serve_file(os.path.join(ROOT, "tv_game.html"))
        if u == "/state":
            return self._j({"targets": status(), "ts": time.strftime("%H:%M:%S")})
        return self._j({"ok": False, "error": "not found"}, 404)

    def do_POST(self):
        u = self.path.split("?")[0].rstrip("/")
        ln = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(ln) or b"{}") if ln else {}
        key = body.get("key")
        if u == "/boot":
            return self._j(boot(key))
        if u == "/stop":
            return self._j(stop(key))
        return self._j({"ok": False, "error": "unknown action"}, 404)

    def serve_file(self, path):
        try:
            with open(path, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self._j({"ok": False, "error": str(e)}, 500)

    def log_message(self, *a):
        pass


def main():
    os.chdir(ROOT)
    srv = http.server.ThreadingHTTPServer((HOST, PORT), H)
    print("GAME CONSOLE on http://%s:%d/" % (HOST, PORT))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    # auto-boot the in-process game so the TV has something to show immediately
    boot("game")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        for k in list(PROC):
            stop(k)
        srv.shutdown()


if __name__ == "__main__":
    main()
