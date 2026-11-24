# session-context

Devin plugin `session-context-analysis`: measures a Devin session's context window (token growth per step, per-source breakdown, biggest tools, tool-definition overhead and ACUs) and draws a colour-coded SVG chart from the session's `context_growth_update` events.

## Layout

- `.devin-plugin/plugin.json` – plugin manifest
- `skills/session-context-analysis/SKILL.md` – skill instructions, including the inline fetch script for `scripted_tools`
- `skills/session-context-analysis/analyze.py` – analysis script: `python3 analyze.py <session-id> [--repo | --no-repo]`

## Install

Install this directory as a Devin plugin (e.g. `manage_plugin` kind=plugin with this repo as the source), then ask Devin to analyse a session's context.
