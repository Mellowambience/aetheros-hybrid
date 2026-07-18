# Alters — Roles & Standing Jobs

Every alter has a role, an owned domain, and a **recurring job** driven by
`fleet_pulse.py` (every 30s) through the real dispatch path. No alter is dormant:
each produces observable activity + evidence in `agent_activity.json`.

| Alter | Role | Owns | Standing Job (recurring) | Real Action |
|-------|------|------|--------------------------|-------------|
| **Hermes** | Runtime | tools, cron, gateway, memory | Orchestrate fleet heartbeat — emit health probe to Steward | appends a slime signal hermes→steward |
| **Steward** | Truth | state.json, metrics, SLA | Read live state, report SLA/drift | reads state.json, reports SLA % |
| **AetherDeck** | Command | dashboard, task inbox | Dashboard pulse — report inbox load | counts queued/done commands |
| **AetherQuest** | Life RPG | quests, XP, grove | Report quest progress / XP | counts done vs total quests |
| **FairyOS** | Shell | desktop OS, themes | Theme heartbeat | writes theme_request heartbeat |
| **EchoVoice** | Voice | local TTS, consents | Report gate status | checks consent file; honest OFFLINE if not installed |
| **Brain** | Knowledge | gbrain, archive | Index life's work | reads works.json, counts repos |
| **Companion** | Presence | mood, reflections | Reflection | logs a calm presence line |
| **Analyst** | Insight | trends | Trend report | counts recent fleet activity, names busiest alter |

## Design notes
- All jobs are **local-only, non-destructive, no network**. Safe to run forever.
- EchoVoice is honestly OFFLINE until `echo_voice` is installed + a consent file
  exists; the pulse reports that state rather than pretending to speak.
- Approved repo-backed quests (via the Quests tab) run a real `_repo_probe`
  (git status) on top of these recurring jobs.
- The pulse writes a `queued` command per alter, then `POST /dispatch` executes it
  via `agents/handlers.py`. Evidence = the resulting `agent_activity.json` row.
