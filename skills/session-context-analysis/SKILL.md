---
name: session-context-analysis
description: "Measure a Devin session's context window: token growth per step, per-source breakdown, biggest tools, tool-definition overhead and ACUs, with a colour-coded SVG bar chart, from the session's context_growth_update events."
---

# Session context analysis

Use when asked how big a session's context is, what fills it, or why it grew. Works for this session or any session the user can access.

## Steps

1. Get the session ID (`devin-...`; for the current session use the `devin_id` from your identity block).
2. **Fetch** with `scripted_tools`: run the script below inline, replacing `SESSION_ID`. It saves the events to `~/session-context-<id>.json` and prints only a count, so raw events never enter your context. (`scripted_tools` only allows tool calls in inline code, which is why this part stays here.)
3. **Analyse** with `exec`; the analysis code ships next to this file and is not read into context:

   ```bash
   python3 "$(find /opt/.devin/plugins_cache -path '*skills/session-context-analysis/analyze.py' -printf '%T@ %p\n' | sort -nr | head -1 | cut -d' ' -f2-)" <session-id>
   ```

   It prints Markdown tables (for sessions over 30 steps, only notable steps), writes the full report to `~/session-context-<id>.md` and the chart to `~/session-context-<id>.svg`. Do not `cat` analyze.py.
4. Send the tables in `message_user` and attach only the SVG (it renders inline and shows exact counts on hover). Do not also attach a PNG or screenshot of it. Add the accuracy caveats below and label measured vs inferred numbers. Read the .md only if the user asks about a step that was left out.
5. Before explaining a spike or drop, read the step's Note and "Tools called" columns. Never call a drop a summary, or a jump a tool load, unless the script labels it so.

## Fetch script

```python
import json, re, os
SESSION_ID = "devin-REPLACE_ME"
ids, after = [], None
while True:
    kw = dict(action="list", session_id=SESSION_ID, event_types=["context_growth_update"], first=100)
    if after: kw["after"] = after
    page = await tools.devin_session_events(**kw)
    ids += re.findall(r"^\[(event-[0-9a-z]+)\]", page, re.M)
    m = re.search(r"after=(\S+?)\s", page)
    if not m: break
    after = m.group(1)
events = []
for i in range(0, len(ids), 20):  # details accepts at most 20 ids
    r = await tools.devin_session_events(action="details", session_id=SESSION_ID, event_ids=ids[i:i+20], max_content_length=50000)
    events += [json.loads(b) for b in re.findall(r"contents: (\{.*?\n\})", r, re.S)]
info = await tools.devin_session_interact(action="get", session_id=SESSION_ID)
acus = re.search(r"acus_consumed: ([\d.]+)", info)
path = os.path.expanduser(f"~/session-context-{SESSION_ID.removeprefix('devin-')}.json")
json.dump({"events": events, "acus": float(acus.group(1)) if acus else None}, open(path, "w"))
print(f"{len(events)} snapshots saved to {path}")
```

## Reading the output

- One `context_growth_update` event is logged after each agent step; a row is the context going into the next step.
- `current_context_tokens` is the total context; how it is counted is undocumented, so call it "logged", not "exact". It can be wrong for a single step.
- **Anomalous reading (red dashed line):** tokens jump >10k with no matching byte growth, then fall back at the next step while bytes keep growing. Treat it as a bad reading, not real content. The script replaces it with the average of its neighbours, so the next step's Δ is not a false drop. Report the logged value, but don't explain it as tool loading or summarising.
- **Drop (green dashed marker, labelled with the Δ):** the per-step axis starts at 0, so drops are markers, not negative bars. A drop counts as a summary or trim only when bytes also fell. If tokens fell while bytes grew, it is a recount and nothing was removed.
- **Tool search (amber):** used only when `__tool_search__` was called at that step or the one before. Each loaded tool costs roughly 1-3k tokens for the rest of the session. A large Δ tokens with small Δ bytes and no tool search stays indigo, with a note.
- "Tools called" lists the calls made since the previous snapshot. Use it to say which step did what.
- Byte counts are exact. Per-tool and per-source tokens are just bytes / 4 (`approx_ant_tokens`).
- `tool_aggregates` also counts tool calls made inside `scripted_tools`, whose output never entered the context; compare with the Δ bytes column before blaming a tool. Image outputs (e.g. `view_image`) show few bytes but real tokens.
- Tool definitions are counted in tokens but not in bytes. The "unitemised" figure estimates them; it also absorbs bytes/4 error on JSON and code, so it drifts up over long sessions. Treat it as an upper bound. It is taken from the last non-anomalous step.
- Bottom chart: one stacked bar of the context at the last normal step. Sky blue = conversation + tool I/O, amber = tool-definition estimate, green = summary of earlier context (`compaction`, shown only after a summary), dark slate = system prompt, fuchsia = memory (`memory_drive`), dark teal = AGENTS.md + repo rules, greys = the four largest other fixed sources plus one segment for the rest, each with its own legend row under "fixed overhead".
- **AGENTS.md and repo rules** have no source field of their own; they are counted under `rules` together with plugin and org rules. The script treats `rules` present at the first snapshot as "rules (at start)" and anything added later as "AGENTS.md + repo rules", and lists each load. A load is the file size plus about 150 B of wrapper. To name the file, compare the load sizes with the repo's `AGENTS.md`, `.devin/rules/`, `.windsurf/rules/` and similar files (e.g. `gh api "repos/<owner>/<repo>/git/trees/HEAD?recursive=1" --jq '.tree[] | "\(.path) \(.size)"'`). If the repo was opened before the first snapshot, its AGENTS.md sits in "rules (at start)"; say so. When nothing was loaded, the segment stays in the legend at 0. If the session did repo work (guessed from git tools being called), the script also prints an advisory to add an AGENTS.md and repo rules; pass it on to the user. If you know the guess is wrong (e.g. repo work done only through `exec`), re-run with `--repo` or `--no-repo` after the session ID. Shares under 0.5% show as "<1%".
- Top chart: bars = tokens added at each step (first step shown as the 'start' value); dark line = running total on the right axis. The left axis is a per-step change and starts at 0; drops are dashed markers.
- Speed per step is in `iteration_stats` events (ttft_ms, inference_ms, tool_exec_ms) if the user asks about latency.
- For dollar figures from ACUs, invoke the `reporting-devin-costs` skill first.

## Limits

- Gives sizes, not the prompt text itself.
- Only sessions the caller can read.
- Older sessions may lack these events; say so instead of guessing.
- The events don't record why a reading is anomalous; say the cause is unknown.
