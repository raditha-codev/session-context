# session-context

Devin plugin `session-context-analysis`: measures a Devin session's context window (token growth per step, per-source breakdown, biggest tools, tool-definition overhead and ACUs over time) and draws a colour-coded SVG chart from the session's `context_growth_update` and `acu_consumption_at_last_user_interaction` events.

## Layout

- `.devin-plugin/plugin.json` – plugin manifest
- `skills/session-context-analysis/SKILL.md` – skill instructions, including the inline fetch script for `scripted_tools`
- `skills/session-context-analysis/analyze.py` – analysis script: `python3 analyze.py <session-id> [--repo | --no-repo]`

## Install

This directory uses the Devin plugin layout (`.devin-plugin/plugin.json` + `skills/`), so it can be uploaded as a personal or org plugin. Then ask Devin to analyse a session's context.
