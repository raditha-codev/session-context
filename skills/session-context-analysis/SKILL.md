---
name: session-context-analysis
description: "Measure a Devin session's logged context growth, source sizes, tool output and ACUs over time, with an interactive HTML chart."
---

# Session context analysis

Use when asked how big a session's context is, what fills it, or why it grew. Works for this session or any session the user can access.

## Steps

1. Get the session ID (`devin-...`; for the current session use the `devin_id` from your identity block).
2. **Fetch** with `scripted_tools`. Run the JavaScript below inline with `SESSION_ID` set to the target session. It saves the events to `~/.cache/session-context/session-context-<id>.json` and prints only the counts and path.
3. **Analyse** with `exec`. Replace `<skill-base-directory>` with the base directory shown when you invoked this skill.

   ```bash
   python3 "<skill-base-directory>/analyze.py" "<session-id>"
   ```

   It prints Markdown tables (for sessions over 30 steps, only notable steps), writes the full report and chart to `~/.cache/session-context/session-context-<id>.md` and `.html` (an SVG chart wrapped in HTML so hover tooltips work in the sidebar). It keeps files for only the 5 most recently analysed sessions and deletes older ones. Do not `cat` analyze.py.
4. Send the tables in `message_user` and attach only the .html chart (it opens in the sidebar and shows exact counts on hover). Attach nothing else: no .md, .json, PNG or screenshot. Add the accuracy caveats below and label measured vs inferred numbers. Read the .md only if the user asks about a step that was left out.
5. Before explaining a spike or drop, check the logged deltas and the tools called. Qualify the cause if telemetry only shows a correlation.

## Fetch script

```javascript
const { mkdir, rename, rm, writeFile } = await import("node:fs/promises");
const { homedir } = await import("node:os");
const { join } = await import("node:path");
const { randomUUID } = await import("node:crypto");

const SESSION_ID = "devin-REPLACE_ME";
const sessionKey = SESSION_ID.replace(/^devin-/, "");
if (!/^[a-f0-9]{32}$/i.test(sessionKey)) throw new Error("Expected a Devin session ID.");

function resultText(response) {
  const result = response.structuredContent?.result ?? response.content?.[0]?.text;
  if (response.isError || typeof result !== "string") throw new Error("Could not read session telemetry.");
  return result;
}

async function fetchEvents(type) {
  const ids = new Set();
  const cursors = new Set();
  let after;
  do {
    const page = resultText(await tools.devin_session_events({
      action: "list", session_id: SESSION_ID, event_types: [type], first: 100,
      ...(after ? { after } : {}),
    }));
    if (page.startsWith("No events found for this session")) break;

    const pageIds = [...page.matchAll(/^\[(event-[a-z0-9-]+)\]/gm)].map(match => match[1]);
    const count = page.match(/^Showing (\d+)\b/);
    if (!count || Number(count[1]) !== pageIds.length) throw new Error("Incomplete list of " + type + " events.");
    for (const id of pageIds) ids.add(id);

    after = page.match(/^More results available\. Pass after=(\S+)/m)?.[1];
    if ((page.includes("More results available.") && !after) || cursors.has(after)) {
      throw new Error("Invalid pagination cursor for " + type + " events.");
    }
    if (after) cursors.add(after);
  } while (after);

  const eventIds = [...ids];
  const events = [];
  for (let i = 0; i < eventIds.length; i += 20) {
    const batch = eventIds.slice(i, i + 20);
    const details = resultText(await tools.devin_session_events({
      action: "details", session_id: SESSION_ID, event_ids: batch, max_content_length: 50000,
    }));
    const blocks = details.split(/^--- (event-[a-z0-9-]+) ---\r?$/m);
    const parsed = new Map();
    for (let j = 1; j < blocks.length; j += 2) {
      const block = blocks[j + 1];
      const marker = block.match(/^  contents:[ \t]*/m);
      if (!marker) continue;
      const event = JSON.parse(block.slice(marker.index + marker[0].length));
      if (event.type === type) parsed.set(blocks[j], event);
    }
    for (const id of batch) {
      if (!parsed.has(id)) throw new Error("Missing " + type + " details for " + id + ".");
      events.push(parsed.get(id));
    }
  }
  return events;
}

const [events, acuEvents] = await Promise.all([
  fetchEvents("context_growth_update"),
  fetchEvents("acu_consumption_at_last_user_interaction"),
]);
const info = resultText(await tools.devin_session_interact({ action: "get", session_id: SESSION_ID }));
const total = info.match(/^[ \t]*acus_consumed:[ \t]*(\S+)/m);
const acus = total ? Number(total[1]) : null;
if (total && !Number.isFinite(acus)) throw new Error("Invalid session ACU total.");
const fetched_at = new Date().toISOString();
const acu_points = acuEvents.map(({ timestamp, amount }) => [timestamp, amount]);

const cache = join(homedir(), ".cache", "session-context");
await mkdir(cache, { recursive: true, mode: 0o700 });
const path = join(cache, "session-context-" + sessionKey + ".json");
const temp = join(cache, "." + sessionKey + "-" + randomUUID() + ".tmp");
try {
  await writeFile(temp, JSON.stringify({ events, acus, acu_points, fetched_at }), { mode: 0o600 });
  await rename(temp, path);
} finally {
  await rm(temp, { force: true });
}
text(events.length + " context snapshots and " + acu_points.length + " ACU readings saved to " + path);
```

## Reading the output

- A `context_growth_update` snapshot records the context after a step. The chart and table use the logged `current_context_tokens` and deltas between consecutive snapshots. The start label shows the first snapshot, and dashed markers show token drops.
- **Possible anomalous reading (red).** A spike over 10,000 tokens that nearly reverts at the next snapshot while bytes stay steady or rise can be a measurement anomaly. The chart keeps the logged readings and flags the affected deltas.
- **Token drop (green).** Check the change in bytes and the `compaction` source before describing a drop. Report the observed changes and qualify any inference about what caused them.
- **Tool search nearby (amber).** Token growth exceeded twice the byte-based estimate and a tool search occurred at that step or the previous one. Treat the search as a clue about timing.
- **Tool output.** The table ranks tools by logged output bytes. Aggregates can include nested `scripted_tools` calls, and image output can use tokens with few reported bytes. Use context deltas and the step's tool calls to investigate growth.
- **Source breakdown.** The chart shows byte counts and byte shares at the last snapshot. Other context is the difference between total context bytes and the sum of named sources. It can include conversation and tool activity. Tool aggregates can overlap, so use them separately to rank output sizes. The text report shows the difference between logged tokens and the bytes / 4 estimate separately from the source breakdown.
- **Rules.** The `rules` source combines repository, plugin and other rules. The table shows changes to that aggregate. Name an individual source only if another event identifies it.
- **ACUs.** Historical readings are plotted in pink. Joining the readings helps track their order in time. Deltas describe intervals between readings. The session total when fetched is a separate diamond without an interval delta. Some sessions have no historical readings.
- **No context snapshots.** The message is “Context snapshots are not available for this session.” If ACU readings or a session total are available, the report and chart show the notice and only ACU data, and the terminal prints any historical ACU readings. No context sizes are inferred.
- For step latency, check `iteration_stats` events (`ttft_ms`, `inference_ms`, `tool_exec_ms`). For dollar figures from ACUs, invoke the `reporting-devin-costs` skill first.

## Limits

- Gives sizes, not the prompt text itself.
- Only sessions the caller can read.
- Sessions may lack context snapshots. If they also have no ACU readings or total, no report or chart is generated.
- The events don't record why a reading is anomalous; say the cause is unknown.
