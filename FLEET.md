# AetherOS Fleet — Federated Agent Constitution

Local-first, peer-agent fleet. No single "boss." Each agent owns a scope and
may spawn task subagents on demand. Hermes is the execution runtime; AetherOS
Steward is the truth/observation layer. Coordination is by request routing, not
command hierarchy.

## Agents (all peer-level)

### hermes — Runtime
- role: agent execution, tools, cron, gateway, memory, delegation
- owns: ~/.hermes, tool calls, scheduled jobs, user preferences
- delegates_subagent_when: a task needs isolation, parallelism, or a bounded context window
- trust: core

### steward — Truth / Observation
- role: probe real services, compute soft SLA, write state.json, detect drift
- owns: AetherOS_Hybrid/state.json, steward.py, metrics, SLA
- delegates_subagent_when: a deep health scan of one service is needed
- trust: core

### aetherdeck — Command Surface
- role: live commander dashboard (port 8788), fleet eye, task curation
- owns: AetherDeck UI, task inbox, release/park gate
- delegates_subagent_when: a task needs execution by another agent
- trust: core

### aetherquest — Life RPG
- role: turn real actions into quests, XP, Memory Grove growth
- owns: AetherQuest/, quest engine, grove state (local save)
- delegates_subagent_when: generating lore, milestones, realm visuals
- trust: project

### fairyos — Living Shell
- role: weather-adaptive desktop OS, calm motion, realm navigation
- owns: FairyOS/, fairy-os-app/
- delegates_subagent_when: building a themed widget or realm view
- trust: project

### echovoice — Local Voice
- role: local Qwen3-TTS, consent-gated, provenance-bound speech
- owns: echo_voice service (:8787), voice profiles, consents
- delegates_subagent_when: never to cloud; only local model calls
- trust: sensitive (biometric)

### brain — Knowledge
- role: GBrain + Living Archive; citations, gap analysis, graph retrieval
- owns: ~/gbrain, amara-living-archive/, world knowledge
- delegates_subagent_when: enrichment, dream-cycle consolidation
- trust: project

### companion — Presence
- role: Mist/Nyx/Aurelia gentle guide; celebrates, never pressures
- owns: companion mood, reflection lines
- delegates_subagent_when: fetching context from brain or steward
- trust: project

## Routing rule
Incoming request -> match owner agent by scope keywords. If no single owner,
steward observes and the request fans out to candidates; aetherdeck curates the
result before release. High-impact/external actions require human gate.
