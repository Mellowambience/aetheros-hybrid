#!/usr/bin/env python3
"""
AetherOS Fleet Router — pure routing logic + fleet.json generator.
Given a request string, returns the owning peer agent and whether a
task subagent should be spawned. No cloud, no model call required for routing.
"""
from __future__ import annotations
import json, sys, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Built-in core peers (cannot be removed by the wizard)
CORE_FLEET = [
    {"id":"hermes","name":"Hermes","role":"Runtime","owns":"tools, cron, gateway, memory",
     "keywords":["tool","cron","gateway","memory","delegate","schedule","run command","execute"],
     "subagent_when":"task needs isolation / parallelism / bounded context"},
    {"id":"steward","name":"AetherOS Steward","role":"Truth","owns":"state.json, metrics, SLA",
     "keywords":["sla","metric","health","status","probe","drift","uptime","monitor"],
     "subagent_when":"deep single-service health scan"},
    {"id":"aetherdeck","name":"AetherDeck","role":"Command","owns":"dashboard, task inbox",
     "keywords":["dashboard","task","release","park","vet","command","fleet eye"],
     "subagent_when":"task needs execution by another agent"},
    {"id":"aetherquest","name":"AetherQuest","role":"Life RPG","owns":"quests, XP, grove",
     "keywords":["quest","xp","level","grove","realm","achievement","habit","journal"],
     "subagent_when":"generate lore / milestone / realm visuals"},
    {"id":"fairyos","name":"FairyOS","role":"Shell","owns":"desktop OS, themes",
     "keywords":["theme","weather","desktop","widget","motion","fairy","realm view"],
     "subagent_when":"build themed widget or realm view"},
    {"id":"echovoice","name":"Echo Voice","role":"Voice","owns":"local TTS, consents",
     "keywords":["voice","tts","speak","synthesize","clone","audio","speech"],
     "subagent_when":"NEVER to cloud; local model call only"},
    {"id":"brain","name":"Knowledge Brain","role":"Knowledge","owns":"gbrain, archive",
     "keywords":["knowledge","remember","search brain","cite","gap","graph","archive","note"],
     "subagent_when":"enrichment / dream-cycle consolidation"},
    {"id":"companion","name":"Companion","role":"Presence","owns":"mood, reflections",
     "keywords":["companion","mood","celebrate","reflect","guide","encourage"],
     "subagent_when":"fetch context from brain or steward"},
]

def load_fleet():
    """Core peers + any custom peers added via the wizard (fleet.json)."""
    fleet = list(CORE_FLEET)
    fj = HERE / "fleet.json"
    if fj.exists():
        try:
            data = json.loads(fj.read_text(encoding="utf-8"))
            for a in data.get("agents", []):
                if isinstance(a, dict) and a.get("id") and a["id"] not in {x["id"] for x in fleet}:
                    fleet.append(a)
        except Exception:
            pass
    return fleet

FLEET = load_fleet()

SCOPE_NOTE = "All agents are peer-level. Hermes=runtime, Steward=observer; neither commands the others."


def route(request: str) -> dict:
    req = request.lower()
    scores = []
    for a in FLEET:
        hits = sum(1 for k in a["keywords"] if k in req)
        if hits:
            scores.append((hits, a))
    scores.sort(key=lambda x: -x[0])
    if not scores:
        return {"owner": None, "candidates": [a["id"] for a in FLEET],
                "spawn_subagent": False, "note": "No scope match; steward observes, aetherdeck curates."}
    owner = scores[0][1]
    candidates = [a["id"] for _, a in scores[:3]]
    return {"owner": owner["id"], "owner_name": owner["name"],
            "candidates": candidates, "spawn_subagent": True,
            "subagent_when": owner["subagent_when"], "note": SCOPE_NOTE}


def emit_fleet_json(path: Path):
    # Persist ONLY custom peers (added via wizard) to avoid duplicating core.
    core_ids = {a["id"] for a in CORE_FLEET}
    custom = [a for a in FLEET if a["id"] not in core_ids]
    payload = {
        "schema": "aetheros.fleet.v1",
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "model": "federated-peer",
        "agents": custom,
        "note": SCOPE_NOTE,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def add_peer(peer: dict) -> dict:
    """Add a custom peer (from the wizard) and persist to fleet.json."""
    if not peer.get("id") or not peer.get("name"):
        return {"ok": False, "error": "id and name required"}
    if peer["id"] in {a["id"] for a in CORE_FLEET}:
        return {"ok": False, "error": "id reserved (core peer)"}
    peer.setdefault("role", "Custom")
    peer.setdefault("owns", "")
    peer.setdefault("keywords", [])
    peer.setdefault("subagent_when", "")
    global FLEET
    FLEET = [a for a in FLEET if a["id"] != peer["id"]]
    FLEET.append(peer)
    emit_fleet_json(HERE / "fleet.json")
    return {"ok": True, "agent": peer["id"]}


def self_test():
    cases = [
        ("synthesize voice with Qwen", "echovoice"),
        ("what is the SLA status", "steward"),
        ("add a daily quest to AetherQuest", "aetherquest"),
        ("change Fairy OS weather theme", "fairyos"),
        ("search my knowledge brain for GBrain", "brain"),
        ("run a cron job via Hermes", "hermes"),
        ("show the command dashboard", "aetherdeck"),
        ("companion encourage me", "companion"),
        ("xyzzy nonsense", None),
    ]
    ok = True
    for q, exp in cases:
        r = route(q)
        got = r["owner"]
        status = "PASS" if got == exp else "FAIL"
        if got != exp:
            ok = False
        print(f"{status}  '{q}' -> {got} (expected {exp})")
    print("ALL GOOD" if ok else "FAILURES PRESENT")
    return ok


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(0 if self_test() else 1)
    if "--emit" in sys.argv:
        p = emit_fleet_json(Path(__file__).resolve().parent / "fleet.json")
        print("wrote fleet.json with", len(p["agents"]), "peer agents")
    else:
        # default: route from stdin/arg
        q = sys.argv[1] if len(sys.argv) > 1 else "synthesize voice"
        print(json.dumps(route(q), indent=2))
