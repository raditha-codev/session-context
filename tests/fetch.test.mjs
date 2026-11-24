import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";

const sessionId = "feedfacefeedfacefeedfacefeedface";
const contextType = "context_growth_update";
const acuType = "acu_consumption_at_last_user_interaction";
const skill = await readFile(new URL("../skills/session-context-analysis/SKILL.md", import.meta.url), "utf8");
const source = skill.match(/^```javascript\n([\s\S]*?)^```$/m)[1];
const cacheLocation = 'join(homedir(), ".cache", "session-context")';
assert.ok(source.includes(cacheLocation));
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const fetch = new AsyncFunction("tools", "text", "cacheDir", source
  .replace("devin-REPLACE_ME", "devin-" + sessionId)
  .replace(cacheLocation, "cacheDir"));

function fixtures() {
  const contextEvents = Array.from({ length: 101 }, (_, index) => ({
    id: "event-c" + index, type: contextType,
    current_context_tokens: index, timestamp: new Date(index * 1000).toISOString(),
  }));
  const acuEvents = Array.from({ length: 103 }, (_, index) => ({
    id: "event-a" + index, type: acuType,
    amount: index / 10, timestamp: new Date(index * 1000).toISOString(),
  }));
  const byId = new Map([...contextEvents, ...acuEvents].map(event => [event.id, event]));
  const listed = [];

  function envelope(result) {
    return { structuredContent: { result }, isError: false };
  }

  return {
    listed,
    tools: {
      async devin_session_events({ action, event_types, first, after, event_ids }) {
        if (action === "list") {
          const [type] = event_types;
          const events = type === contextType ? contextEvents : acuEvents;
          const offset = after ? Number(after) : 0;
          const page = events.slice(offset, offset + first);
          listed.push([type, offset]);
          const more = offset + first < events.length
            ? "\nMore results available. Pass after=" + (offset + first) + " to fetch the next page."
            : "";
          return envelope("Showing " + page.length + more + "\n\n" +
            page.map(({ id }) => "[" + id + "] 2026-11-24 11:00:00 UTC").join("\n"));
        }
        assert.equal(action, "details");
        assert.ok(event_ids.length <= 20);
        const blocks = event_ids.map(id => "--- " + id + " ---\n  contents: " + JSON.stringify(byId.get(id), null, 2));
        return envelope("Event details (" + event_ids.length + " events):\n\n" + blocks.join("\n\n"));
      },
      async devin_session_interact() {
        return envelope("Session details:\n  acus_consumed: 1.25e1\n");
      },
    },
  };
}

test("the documented fetcher follows both streams past 100 events", async () => {
  const cache = await mkdtemp(join(tmpdir(), "session-context-fetch-"));
  try {
    const { listed, tools } = fixtures();
    const log = [];
    await fetch(tools, message => log.push(message), cache);
    const data = JSON.parse(await readFile(join(cache, "session-context-" + sessionId + ".json"), "utf8"));
    assert.deepEqual(listed.filter(([type]) => type === contextType), [[contextType, 0], [contextType, 100]]);
    assert.deepEqual(listed.filter(([type]) => type === acuType), [[acuType, 0], [acuType, 100]]);
    assert.equal(data.events.length, 101);
    assert.equal(data.events.at(-1).current_context_tokens, 100);
    assert.equal(data.acu_points.length, 103);
    assert.equal(data.acu_points.at(-1)[1], 10.2);
    assert.equal(data.acus, 12.5);
    assert.equal(log.length, 1);
    assert.match(log[0], /^101 context snapshots and 103 ACU readings saved/);
  } finally {
    await rm(cache, { recursive: true, force: true });
  }
});
