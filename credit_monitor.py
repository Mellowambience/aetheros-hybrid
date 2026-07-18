#!/usr/bin/env python3
"""
AetherOS Credit Monitor — watches cloud model providers for available credit.
Local-first watchdog: probes each configured provider with a minimal
completion call and records state to credit_status.json (read by the dashboard).

Why a completion call and not /v1/models?
  zyloo's /v1/models returns 200 even with ZERO balance. Only a real
  completion reveals 402 (no credit) vs 200 (credit). So we probe with
  max_tokens=1 — the cheapest possible signal. When credit is absent the
  call is free (402). When present it costs ~1 token (negligible heartbeat).

Providers:
  zyloo       : reads ZYLOO_KEY from .env, base https://api.zyloo.io/v1
  tokenrouter : reads TOKENROUTER_KEY from .env (optional), base from
                TOKENROUTER_BASE_URL or default https://api.tokenrouter.com/v1

States per provider:
  credit        -> 200, can route cloud models
  no_credit     -> 402, key valid but balance empty
  key_invalid   -> 401
  not_configured-> no key in .env
  error         -> network/other

Run:
  python credit_monitor.py            # serve loop (default 300s interval)
  python credit_monitor.py --once     # single check, write json, exit
  python credit_monitor.py --interval 120
"""
from __future__ import annotations
import argparse, json, os, re, sys, time
from pathlib import Path
from datetime import datetime, timezone

HERE = Path(__file__).resolve().parent
ENV = Path.home() / ".hermes" / ".env"
OUT = HERE / "credit_status.json"
INTERVAL = 300
PROBE_MODEL = "zyloo/claude-opus-4-7"   # known-valid id; cheapest credit signal (max_tokens=1)
TR_PROBE_MODEL = "glm-5.2"          # TokenRouter free model per promo


def load_env() -> dict:
    d = {}
    if ENV.exists():
        for line in ENV.read_text(encoding="utf-8", errors="ignore").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                d[k.strip()] = v.strip()
    return d


def probe(base_url: str, key: str, model: str) -> dict:
    import urllib.request, urllib.error
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1,
    }).encode()
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            if r.status == 200:
                return {"state": "credit", "detail": f"200 OK · model {model}"}
            return {"state": "error", "detail": f"unexpected HTTP {r.status}"}
    except urllib.error.HTTPError as e:
        if e.code == 402:
            return {"state": "no_credit", "detail": "402 Payment Required — balance empty"}
        if e.code == 401:
            return {"state": "key_invalid", "detail": "401 — key rejected"}
        if e.code == 400:
            # unknown model OR bad request. If the key is valid (not 401), the
            # account is reachable; a model-parse 400 still proves auth passed,
            # but to be safe we flag it as config_error rather than credit.
            return {"state": "config_error",
                    "detail": f"400 — probe model rejected: {e.read()[:120].decode(errors='ignore')}"}
        return {"state": "error", "detail": f"HTTP {e.code}: {e.read()[:120].decode(errors='ignore')}"}
    except Exception as e:
        return {"state": "error", "detail": str(e)[:120]}


def check_all() -> dict:
    env = load_env()
    out = {"generated_at": datetime.now(timezone.utc).isoformat(), "providers": {}}

    # zyloo
    zk = env.get("ZYLOO_KEY")
    if zk:
        out["providers"]["zyloo"] = {
            "base_url": "https://api.zyloo.io/v1",
            **probe("https://api.zyloo.io/v1", zk, PROBE_MODEL),
        }
    else:
        out["providers"]["zyloo"] = {"state": "not_configured", "detail": "ZYLOO_KEY missing in .env"}

    # tokenrouter (optional)
    tk = env.get("TOKENROUTER_KEY")
    tr_base = env.get("TOKENROUTER_BASE_URL", "https://api.tokenrouter.com/v1")
    if tk:
        out["providers"]["tokenrouter"] = {
            "base_url": tr_base,
            **probe(tr_base, tk, TR_PROBE_MODEL),
        }
    else:
        out["providers"]["tokenrouter"] = {"state": "not_configured",
                                          "detail": "TOKENROUTER_KEY missing in .env (optional)"}

    # agent-routing summary
    any_credit = any(p.get("state") == "credit" for p in out["providers"].values())
    out["cloud_routable"] = any_credit
    out["note"] = ("Cloud models available — agent may route via custom provider."
                   if any_credit else
                   "No cloud credit detected. Agent stays local-first until credit appears.")
    return out


def write(out: dict):
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=int, default=INTERVAL)
    args = ap.parse_args()

    if args.once:
        out = check_all(); write(out)
        print("credit check ->", json.dumps(out["providers"], indent=2))
        print("cloud_routable:", out["cloud_routable"])
        return

    print(f"Credit monitor running (interval {args.interval}s). Writes {OUT}")
    while True:
        try:
            out = check_all(); write(out)
        except Exception as e:
            print("monitor error:", e)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
