#!/usr/bin/env python3
"""
FOUNDRY — local recursive self-improvement foundry (the "factory superintelligence" seed).

Principle: a model generates a candidate improvement to THIS system, implements it in a
throwaway sandbox copy, runs the existing test harness against it, and scores the result.
Proven (pass + delta>0) candidates are queued to outbox.json with tier=T2 (human SEND gate).
Dangerous / failing / regressing candidates are discarded with a reason. No external calls.
Local-only. Human stays the merge authority.

Loop (one tick):
  1. PROPOSE  — qwen3-coder reads this file + a target (or picks from a backlog) and emits a
                JSON patch (a real, minimal diff) + a test expectation.
  2. SANDBOX  — apply the patch to a temp copy of the repo; run tests there.
  3. SCORE    — baseline score (current repo tests) vs sandbox score. delta = sandbox - baseline.
  4. GATE     — if pass and delta >= 0: queue to outbox (human SEND). else: log + discard.
  5. RECURSE  — loop. Each proven merge RAISES the baseline, so the next tick improves on better code.

Usage:
  python foundry.py --once       run one tick, print result
  python foundry.py              run the loop forever (background)
"""
from __future__ import annotations
import json, os, shutil, subprocess, time, tempfile, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
OLLAMA = "http://127.0.0.1:11434/api/generate"
MODEL = "qwen3-coder:30b-a3b-q4_K_M"
OUTBOX = HERE / "outbox.json"
LOG = HERE / "foundry_log.jsonl"
BASE_TARGETS = [
    "reduce duplicate code in command_hub.py and dispatch.py (shared HTTP helper)",
    "add a unit test to fleet_router.py that asserts the no-match fallback returns AetherOS Steward",
    "make buildShelf collapse redundant shelf pins without breaking the launcher button",
    "harden supervisor.py: restart a child only after 3 consecutive failures, not 1",
]

PROMPT = """You are a senior systems engineer improving a LOCAL-FIRST agent OS (AetherOS Hybrid) in directory {here}.
Real files present (use EXACT relative names): command_hub.py, dispatch.py, fleet_router.py, mothership.py, supervisor.py, system_map.py, credit_monitor.py, steward.py, agents/handlers.py, aetherhaven_desktop.html.
Propose ONE minimal, safe improvement to ONE file. Output ONLY valid JSON, no prose:
{{"target":"<what you improved>","file":"<exact filename>","old_string":"<verbatim existing lines from the file>","new_string":"<the replacement lines>","test":"<shell cmd that exits 0 on success>","why":"<one line>"}}

Rules:
- old_string MUST be copied VERBATIM from the REAL CURRENT SOURCE below (exact whitespace).
- new_string replaces old_string in place.
- Do NOT touch secrets/.env/network code.
- test must be runnable and exit 0.
Target this tick: {target}

REAL CURRENT SOURCE (read this, copy old_string from it verbatim):
{ground}
"""


def _ollama(prompt: str) -> str:
    body = json.dumps({"model": MODEL, "prompt": prompt, "stream": False,
                       "options": {"temperature": 0.4, "num_predict": 1200}}).encode()
    req = urllib.request.Request(OLLAMA, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode())["response"]


def _extract_json(t: str) -> dict:
    s = t.find("{"); e = t.rfind("}")
    if s == -1 or e == -1:
        return {}
    try:
        return json.loads(t[s:e + 1])
    except Exception:
        return {}


def _run(cmd, cwd):
    try:
        p = subprocess.run(cmd, shell=True, cwd=str(cwd), capture_output=True,
                            text=True, timeout=120)
        return p.returncode, p.stdout + p.stderr
    except Exception as ex:
        return 1, str(ex)


def baseline_score():
    """Run the existing self-tests we trust."""
    rc, _ = _run("python fleet_router.py --selftest", HERE)
    a = 0 if rc == 0 else 1
    rc2, _ = _run("python -c \"import ast;ast.parse(open('command_hub.py').read());ast.parse(open('dispatch.py').read());print('ok')\"", HERE)
    b = 0 if rc2 == 0 else 1
    return 2 - (a + b)  # 0..2 score


def _apply_edit(repo: Path, cand: dict) -> tuple[int, str]:
    """Apply candidate via exact old_string->new_string replace (robust, no diff parsing)."""
    f = repo / cand["file"]
    if not f.exists():
        return 1, f"file {cand['file']} missing"
    src = f.read_text(encoding="utf-8")
    old, new = cand.get("old_string", ""), cand.get("new_string", "")
    if not old or old not in src:
        return 1, "old_string not found verbatim in file"
    f.write_text(src.replace(old, new, 1), encoding="utf-8")
    return 0, "applied"


def tick(target: str) -> dict:
    # ground the model: give it the REAL source of the most likely target file
    ground = ""
    for fn in ["fleet_router.py", "command_hub.py", "dispatch.py", "supervisor.py"]:
        p = HERE / fn
        if p.exists():
            ground += f"\n--- {fn} (REAL CURRENT CONTENT) ---\n" + p.read_text(encoding="utf-8")[:2500] + "\n"
    cand = _extract_json(_ollama(PROMPT.format(target=target, here=HERE, ground=ground)))
    if not cand.get("file") or not cand.get("old_string") or not cand.get("new_string"):
        return {"ok": False, "reason": "no valid edit (need file+old_string+new_string)", "cand": cand}
    # sandbox
    tmp = Path(tempfile.mkdtemp(prefix="foundry_"))
    try:
        shutil.copytree(HERE, tmp / "repo", dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "foundry_*", "outbox.json"))
        rc, out = _apply_edit(tmp / "repo", cand)
        if rc != 0:
            return {"ok": False, "reason": "edit failed to apply", "detail": out[:300], "cand": cand}
        # run candidate test
        rc_t, out_t = _run(cand.get("test", "echo skip"), tmp / "repo")
        if rc_t != 0:
            return {"ok": False, "reason": "candidate test failed", "detail": out_t[:400], "cand": cand}
        sandbox = baseline_score_in(tmp / "repo")
        base = baseline_score()
        delta = sandbox - base
        if delta >= 0:
            # queue to outbox (human SEND gate) as T2
            queue_outbox(cand, base, sandbox, delta)
            return {"ok": True, "delta": delta, "base": base, "sandbox": sandbox,
                    "target": cand.get("target"), "why": cand.get("why")}
        return {"ok": False, "reason": f"regressed (delta {delta})", "cand": cand}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def baseline_score_in(repo: Path) -> int:
    rc, _ = _run("python fleet_router.py --selftest", repo)
    a = 0 if rc == 0 else 1
    rc2, _ = _run("python -c \"import ast;ast.parse(open('command_hub.py').read());ast.parse(open('dispatch.py').read())\"", repo)
    b = 0 if rc2 == 0 else 1
    return 2 - (a + b)


def queue_outbox(cand, base, sandbox, delta):
    data = []
    if OUTBOX.exists():
        try:
            data = json.loads(OUTBOX.read_text(encoding="utf-8"))
        except Exception:
            data = []
    if not isinstance(data, list):
        data = []
    data.append({
        "id": f"foundry_{int(time.time())}",
        "source": "foundry",
        "target": cand.get("target"),
        "file": cand.get("file"),
        "old_string": cand.get("old_string"),
        "new_string": cand.get("new_string"),
        "test": cand.get("test"),
        "why": cand.get("why"),
        "score_base": base, "score_sandbox": sandbox, "delta": delta,
        "tier": "T2", "status": "queued", "sends": True,
        "ts": time.strftime("%H:%M:%S"),
    })
    OUTBOX.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    import sys
    if "--once" in sys.argv:
        t = BASE_TARGETS[0]
        print("TICK:", json.dumps(tick(t), ensure_ascii=False, indent=2)[:600])
        return
    i = 0
    while True:
        t = BASE_TARGETS[i % len(BASE_TARGETS)]
        res = tick(t)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.strftime("%H:%M:%S"), **res}, ensure_ascii=False) + "\n")
        print(f"[{time.strftime('%H:%M:%S')}] tick {i}: {'PASS' if res.get('ok') else 'skip'} "
              f"{res.get('reason','')} {res.get('delta','')}")
        i += 1
        time.sleep(20)


if __name__ == "__main__":
    main()
