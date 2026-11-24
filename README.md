# session-context

Devin plugin `session-context-analysis` charts a session's logged context tokens, source byte counts, tool output sizes, and ACUs. The interactive HTML chart uses context snapshots and historical ACU events and marks the current session ACU total separately.

## Layout

- `.devin-plugin/plugin.json` – plugin manifest
- `skills/session-context-analysis/SKILL.md` – skill instructions and inline JavaScript fetcher for `scripted_tools`
- `skills/session-context-analysis/analyze.py` – analysis script, run with `python3 analyze.py <session-id>`

## Install

This directory uses the Devin plugin layout (`.devin-plugin/plugin.json` + `skills/`), so it can be uploaded as a personal or org plugin. Then ask Devin to analyse a session's context.
