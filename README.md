# AetherOS Hybrid · Pocket Realm

A **local-first, permissioned, observable agent operating system** — a ChromeOS-Flex-style
desktop shell wrapping a federated fleet of peer AI agents. Built to be *calm, safe, and
alive*: one chat, one launcher, a breathing presence dot, and quiet panels you expand on demand.

> "If it feels busy, cut." — the Aetherhaven art bible. This app defaults to **Calm mode**:
> 9 of 10 panels collapse to title-chips; the Command Deck (truth/SLA) stays as the anchor.

## What it is

- **Pocket Realm UI** (`aetherhaven_desktop.html`) — liquid-glass chat-room desktop with a
  ChromeOS-Flex shelf (launcher + chat + presence), app-grid launcher with fleet search,
  and movable/resizable glass windows.
- **Fleet** — 8 peer agents (Hermes=runtime, Steward=truth, AetherDeck=command, AetherQuest=
  life, FairyOS=shell, Echo Voice, Knowledge Brain, Companion). Federated: none commands the others.
- **Dispatch** — commands route via `fleet_router`, execute locally (T0/T1), or queue to an
  **Outbox** awaiting your SEND (T2 external). The human gate is explicit and never bypassed.
- **Live telemetry** — System Map shows each blueprint node's real runtime state.

## Run it

```bash
python run.py
# → opens http://127.0.0.1:8900/aetherhaven_desktop.html
```

Or run the supervisor directly: `python supervisor.py` (foreground; spawns + self-heals all services).

**Requirements:** Python 3.10+ (stdlib only — no pip install). Loopback-only. No cloud, no keys
for the core app. Optional: set `ZYLOO_KEY` / `TOKENROUTER_KEY` in `~/.hermes/.env` to enable the
Credit Monitor's cloud-balance probe (the app works without them).

## Architecture

| Port | Service | File |
|------|---------|------|
| 8900 | Web app (console server) | `supervisor.py` → `http.server` |
| 8910 | Voice launcher endpoint | `launcher.py` |
| 8911 | Command Hub (route + gate) | `command_hub.py` |
| 8912 | Dispatch (execute / queue) | `dispatch.py` |
| 8913 | System Map (live telemetry) | `system_map.py` |
| 8920 | Mothership (fleet thinking API) | `mothership.py` |

State lives in JSON files (`state.json`, `command_inbox.json`, `agent_activity.json`, …) — all
gitignored. Secrets are **never** in the repo; they stay in `~/.hermes/.env`.

## Controls

- **🔘 Launcher** — app grid + fleet search (the single navigation surface)
- **💬 Chat** — talk to the fleet / command any agent; external actions wait for your SEND
- **◉ Presence** — breathing heartbeat; amber + count when actions await your approval
- **Layout ▾ → 🌿 Calm / ▣ Expand all** — toggle the calm default
- **Theme / Windows / Density / 🔁 Curate** — live theming, window visibility, tinder-style curation

## Credits

Built with Hermes Agent. Local-first by construction.
