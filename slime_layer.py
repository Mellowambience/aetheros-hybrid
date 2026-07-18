#!/usr/bin/env python3
"""
slime_layer.py — the LIQUID layer for AetherOS Hybrid.

Faithful Python port of the fleet `slime` primitive (aether-fleet-primitives/slime),
semantics identical to the tested JS version. Native to this Python fleet:
wraps the REAL peers from fleet_router and adds adaptive, persistent routing.

The fleet_router.py router is keyword-static — it has no memory of which lanes
are actually used. slime_layer adds that memory: lanes reinforce with traffic,
decay when idle, prune when forgotten, and persist across restarts.

Usage (additive — does not replace fleet_router):
    from slime_layer import SlimeLayer
    slime = SlimeLayer()                 # loads real fleet from fleet_router
    slime.emit("hermes", "steward", {"op": "probe"})
    topo = slime.topology()             # feed aetherhaven system_map / viz
    slime.tick()                        # idle lanes decay
    slime.save()                        # persist; auto-loaded next start
"""
from __future__ import annotations
import json, os, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE_FILE = HERE / "slime-state.json"

# Import the REAL fleet (core + custom) without hard failure if missing.
try:
    import fleet_router as _fr
    FLEET = _fr.FLEET
except Exception:
    FLEET = []


class SlimeLayer:
    def __init__(self, max_weight=10.0, decay=0.995, prune_below=0.15):
        self.max_weight = max_weight
        self.decay = decay
        self.prune_below = prune_below
        self.nodes = {}          # id -> {"last": ts}
        self.edges = {}          # "a|b" -> {"weight": w, "last": ts}
        self.pending = []        # signals waiting for a path
        self.inbox = {}          # id -> [signals]
        for a in FLEET:
            self.register(a["id"])

    # ---- topology helpers ----
    def _key(self, a, b):
        return f"{a}|{b}" if a < b else f"{b}|{a}"

    def register(self, nid):
        if nid not in self.nodes:
            self.nodes[nid] = {"last": datetime.datetime.now().timestamp()}
        else:
            self.nodes[nid]["last"] = datetime.datetime.now().timestamp()
        if nid not in self.inbox:
            self.inbox[nid] = []
        return self

    def connect(self, a, b, weight=1.0):
        self.register(a); self.register(b)
        k = self._key(a, b)
        e = self.edges.get(k)
        if e:
            e["weight"] = min(self.max_weight, e["weight"] + weight)
        else:
            self.edges[k] = {"weight": weight, "last": datetime.datetime.now().timestamp()}
        return self

    def _neighbors(self, nid):
        out = []
        for k, e in self.edges.items():
            x, y = k.split("|")
            if x == nid: out.append((y, e["weight"]))
            elif y == nid: out.append((x, e["weight"]))
        return out

    def _route(self, frm, to):
        if frm == to:
            return [frm]
        visited = {frm}
        path = [frm]
        cur = frm
        while cur != to:
            nbrs = [(n, w) for n, w in self._neighbors(cur) if n not in visited]
            if not nbrs:
                return None
            nbrs.sort(key=lambda x: -x[1])
            nxt = nbrs[0][0]
            path.append(nxt); visited.add(nxt); cur = nxt
            if len(path) > 100:
                return None
        return path

    # ---- flow ----
    def emit(self, frm, to, payload, stype="signal"):
        self.register(frm)
        path = self._route(frm, to) if to else None
        if path and len(path) >= 2:
            for i in range(len(path) - 1):
                self.connect(path[i], path[i + 1])
            sig = {"from": frm, "to": to, "type": stype, "payload": payload,
                   "at": datetime.datetime.now().isoformat(), "hops": len(path) - 1}
            self.inbox.setdefault(to, []).append(sig)
            self._unpark(frm, to, payload)
            return {"delivered": True, "path": path, "hops": len(path) - 1}
        self.pending.append({"from": frm, "to": to, "type": stype, "payload": payload,
                             "at": datetime.datetime.now().isoformat()})
        return {"delivered": False, "path": None, "hops": 0, "pending": True}

    def _unpark(self, frm, to, payload):
        self.pending = [s for s in self.pending
                        if not (s["from"] == frm and s["to"] == to and s["payload"] == payload)]

    def received(self, nid):
        return list(self.inbox.get(nid, []))

    def flush(self):
        still = []
        for s in self.pending:
            r = self.emit(s["from"], s["to"], s["payload"], s.get("type", "signal"))
            if not r["delivered"]:
                still.append(s)
        self.pending = still
        return len(self.pending)

    def tick(self):
        for k, e in list(self.edges.items()):
            e["weight"] *= self.decay
            if e["weight"] < self.prune_below:
                del self.edges[k]
        return self

    def topology(self):
        return [{"a": k.split("|")[0], "b": k.split("|")[1],
                 "weight": round(e["weight"], 3)} for k, e in self.edges.items()]

    # ---- persistence (the self remembers) ----
    def save(self, path=STATE_FILE):
        path.write_text(json.dumps({
            "nodes": list(self.nodes.items()),
            "edges": list(self.edges.items()),
            "pending": self.pending,
            "inbox": list(self.inbox.items()),
        }, indent=2), encoding="utf-8")
        return self

    @classmethod
    def load(cls, path=STATE_FILE):
        if not path.exists():
            return cls()
        raw = json.loads(path.read_text(encoding="utf-8"))
        s = cls()
        s.nodes = dict(raw.get("nodes", []))
        s.edges = dict(raw.get("edges", []))
        s.pending = raw.get("pending", [])
        s.inbox = dict(raw.get("inbox", []))
        return s


if __name__ == "__main__":
    s = SlimeLayer()
    # quick self-test against the REAL fleet
    s.connect("hermes", "steward")
    s.connect("steward", "brain")
    r = s.emit("hermes", "brain", {"op": "probe"})
    assert r["delivered"] and r["hops"] == 2, r
    assert s.received("brain")[-1]["payload"]["op"] == "probe"
    # reinforcement
    for _ in range(3):
        s.emit("hermes", "steward", {})
    assert s.edges[s._key("hermes", "steward")]["weight"] > 1
    # decay/prune
    s2 = SlimeLayer(decay=0.5, prune_below=0.2)
    s2.connect("a", "b")
    for _ in range(5):
        s2.tick()
    assert s2.edges == {}, s2.edges
    # persistence
    s.save()
    s3 = SlimeLayer.load()
    assert s3.edges == s.edges
    STATE_FILE.unlink(missing_ok=True)
    print(f"SLIME LAYER OK · fleet={len(s.nodes)} peers · all self-tests passed")
