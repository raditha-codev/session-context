"""Analyse a saved session-context JSON (written by the fetch step in SKILL.md).

Usage: python3 analyze.py <session-id> [--repo | --no-repo]
--repo / --no-repo override the repo-work guess (git tools called) used for the AGENTS.md advisory.
Prints Markdown tables (step table trimmed to notable steps for long sessions),
writes the full report and the chart (session-context-<id>.md / .html, an SVG chart wrapped in HTML with hover tooltips) to ~/.cache/session-context/,
keeping files for only the KEEP most recently analysed sessions.
"""
import json, math, os, sys
from datetime import datetime, timezone
from html import escape as esc

SESSION_ID = sys.argv[1] if sys.argv[1].startswith("devin-") else "devin-" + sys.argv[1]
SID = SESSION_ID.removeprefix("devin-")
OUT, KEEP = os.path.expanduser("~/.cache/session-context"), 5
data = json.load(open(f"{OUT}/session-context-{SID}.json"))
events = sorted(data["events"], key=lambda e: e["timestamp"])
repo_flag = "--repo" in sys.argv or ("--no-repo" not in sys.argv and None)
if not events:
    print("No context_growth_update events for this session."); sys.exit()

_full = []
def print(s="", brief=True):
    _full.append(str(s))
    if brief: sys.stdout.write(str(s) + "\n")

acus = data.get("acus")
print(f"Session {SESSION_ID}: {len(events)} context snapshots" + (f", ACUs {acus:.2f}" if acus is not None else ""))

T = [e["current_context_tokens"] for e in events]
B = [e["current_context_bytes"] for e in events]
n_ev = len(events)
# Glitch: a one-step token spike that reverts at the next step while bytes keep growing.
glitch = set()
for i in range(1, n_ev - 1):
    up, db = T[i] - T[i-1], B[i] - B[i-1]
    if up > 10000 and up > 3 * max(db, 0) / 4 and B[i+1] >= B[i] and (T[i+1] - T[i-1]) < 0.3 * up:
        glitch.add(i)
clean = [((T[i-1] + T[i+1]) // 2 if i in glitch else T[i]) for i in range(n_ev)]

def calls(e): return {a["tool_name"] + (f":{a['action']}" if a.get("action") else ""): a["call_count"] for a in e.get("tool_aggregates", [])}
print("\n| Step | Time (UTC) | Tokens | Δ tokens | Bytes | Δ bytes | Tools called | Note |\n|---|---|---|---|---|---|---|---|")
steps, prev_calls, searched = [], {}, []
for i, e in enumerate(events):
    c = calls(e)
    newc = {k: v - prev_calls.get(k, 0) for k, v in c.items() if v > prev_calls.get(k, 0)}
    prev_calls = c
    searched.append(any("tool_search" in k for k in newc))
    dt = clean[i] - clean[i-1] if i else 0
    db = B[i] - B[i-1] if i else 0
    kind, note = "normal", ""
    if i in glitch:
        kind, note = "glitch", f"anomalous reading (reverts next step, bytes steady); {clean[i]:,} used instead"
    elif i and dt < 0 and db < 0: kind, note = "shrink", "context shrank (summary/trim)"
    elif i and dt < 0: kind, note = "recount", "token count fell while bytes grew: recount, nothing removed"
    elif i and dt > 2000 and dt > 2 * max(db, 0) / 4:
        if searched[i] or searched[i-1]: kind, note = "tools", "tool search: tool definitions loaded"
        else: note = "tokens grew faster than bytes/4 (no tool search; dense content or recount)"
    if i - 1 in glitch: note = (note + "; " if note else "") + "Δ vs corrected previous step"
    steps.append((i + 1, clean[i], dt, kind, T[i]))
    notable = n_ev <= 30 or i in (0, n_ev - 1) or bool(note) or abs(dt) >= max(2000, 0.05 * max(T))
    print(f"| {i+1} | {e['timestamp'][11:19]} | {T[i]:,} | {dt:+,} | {B[i]:,} | {db:+,} | {', '.join(f'{k}×{v}' for k, v in newc.items())} | {note} |", brief=notable)
if n_ev > 30: print(f"\n(Only notable steps shown; all {n_ev} steps are in {OUT}/session-context-{SID}.md.)")
# ACU series: running total logged at each user message, plus the total at fetch time.
ts = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
acu_pts = sorted((ts(t), a) for t, a in data.get("acu_points", []))
acu_now = acus is not None and bool(data.get("fetched_at")) and (not acu_pts or ts(data["fetched_at"]) > acu_pts[-1][0])
if acu_now: acu_pts.append((ts(data["fetched_at"]), acus))
if acu_pts:
    print(f"\nACUs (running total at each user message{'; last row is the total when fetched' if acu_now else ''}):\n\n| Time (UTC) | ACUs | Δ ACUs |\n|---|---|---|", brief=len(acu_pts) <= 20)
    for j, (t, a) in enumerate(acu_pts):
        print(f"| {datetime.fromtimestamp(t, timezone.utc):%H:%M:%S} | {a:.2f} | {a - (acu_pts[j-1][1] if j else 0):+.2f} |", brief=len(acu_pts) <= 20)
if glitch: print(f"\nAnomalous token readings at step(s) {', '.join(str(i+1) for i in sorted(glitch))}: excluded from deltas, totals and chart.")

li = max(i for i in range(n_ev) if i not in glitch)
last = events[li]
src = last.get("per_source_context_bytes", {})
rest = last["current_context_bytes"] - sum(src.values())
unitemised = max(0, int(T[li] - B[li] / 4))
print(f"\nBreakdown at step {li+1}:\n\n| Source | Bytes | ≈Tokens (B/4) |\n|---|---|---|")
for k, v in sorted(src.items(), key=lambda kv: -kv[1]):
    print(f"| {k} | {v:,} | {v//4:,} |")
print(f"| conversation + tool I/O | {rest:,} | {rest//4:,} |")
print(f"| unitemised (≈tool definitions) | – | {unitemised:,} |")

# AGENTS.md and repo rules are counted under "rules"; rules loaded after the first snapshot are repo files the agent opened.
rules_start = min(events[0].get("per_source_context_bytes", {}).get("rules", 0), src.get("rules", 0))
repo_rules = src.get("rules", 0) - rules_start
loads, pr, pc = [], events[0].get("per_source_context_bytes", {}).get("rules", 0), calls(events[0])
for i, e in enumerate(events[1:li + 1], 1):
    rb, c = e.get("per_source_context_bytes", {}).get("rules", 0), calls(e)
    if rb > pr: loads.append((i + 1, e["timestamp"][11:19], rb - pr, ", ".join(f"{k}×{v - pc.get(k, 0)}" for k, v in c.items() if v > pc.get(k, 0))))
    pr, pc = rb, c
if loads:
    print("\nRules loaded during the session (AGENTS.md / repo rules; each ≈ file size + ~150 B wrapper):\n\n| Step | Time (UTC) | Δ rules bytes | Tools called |\n|---|---|---|---|")
    for row in loads: print(f"| {row[0]} | {row[1]} | {row[2]:+,} | {row[3]} |")

used_tools = {a["tool_name"] for e in events for a in e.get("tool_aggregates", [])}
repo_used = repo_flag if repo_flag is not None else any(t.startswith("git_") or t == "fetch_pr_template" for t in used_tools)
if not loads:
    print("\nNo AGENTS.md or repo rules were loaded after the first snapshot (if the repo was opened earlier they sit in rules at start).")
    print(" Advisory: add an AGENTS.md and repo rules (e.g. .devin/rules/) so the agent gets the repo's conventions." if repo_used else
          " No repo work detected (no git tools called), so no AGENTS.md advisory. Re-run with --repo if the session did work in a repo.")
print("\n| Tool | Calls | Output bytes | ≈Tokens |\n|---|---|---|---|")
for a in sorted(events[-1].get("tool_aggregates", []), key=lambda a: -a["total_output_bytes"]):
    name = a["tool_name"] + (f":{a['action']}" if a.get("action") else "")
    print(f"| {name} | {a['call_count']} | {a['total_output_bytes']:,} | {a.get('approx_ant_tokens', a['total_output_bytes']//4):,} |")

print(f"\nUnitemised tokens (tokens - bytes/4, mostly tool definitions): first {T[0] - B[0] / 4:,.0f}, step {li+1} {unitemised:,}")

# ---- SVG chart (pure Python) ----
def nice(v):
    m = 10 ** math.floor(math.log10(max(v, 1)))
    return next(f * m for f in (1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10) if f * m >= v)

C = {"total": "#0F172A", "normal": "#6366F1", "tools": "#F59E0B", "shrink": "#10B981", "recount": "#10B981", "glitch": "#EF4444",
     "fixed": "#94A3B8", "conversation": "#0EA5E9", "tooldefs": "#F59E0B", "memory": "#D946EF", "reporules": "#0F766E", "sysprompt": "#334155", "summary": "#10B981", "acu": "#DB2777"}
INK, MUTED, GRID, W, P = "#0F172A", "#64748B", "#E2E8F0", 960, 70
out = []
def text(x, y, s, size=12, fill=MUTED, anchor="start", weight="normal"):
    out.append(f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}" text-anchor="{anchor}" font-weight="{weight}">{esc(str(s))}</text>')
def legend(y, items):
    x = P
    for k, lab in items:
        if x + 18 + 6.2 * len(lab) > W - 10: x, y = P, y + 20
        out.append(f'<rect x="{x}" y="{y-10}" width="12" height="12" rx="2" fill="{C[k]}"/>'); text(x + 18, y, lab); x += 34 + 6.2 * len(lab)
    return y

h1, top1, PR = 300, 70, (130 if acu_pts else 70)
def k(v): return f"{v/1000:g}k" if v else "0"
bars = steps[1:] or steps
# The per-step axis starts at 0; drops (summary/recount) are drawn as labelled dashed markers, not negative bars.
d = [max(b[2], 0) for b in bars]
hi, lo = max(max(d), 1) * 1.1, 0
dstep = nice((hi - lo) / 5)
dmin, dmax = math.floor(lo / dstep) * dstep, math.ceil(hi / dstep) * dstep
N = round((dmax - dmin) / dstep)
tmax = nice(max(s[1] for s in steps) * 1.05 / N) * N
yd = lambda v: top1 + h1 * (dmax - v) / (dmax - dmin)
yt = lambda v: top1 + h1 * (1 - v / tmax)
text(P, 32, f"Tokens added per step{' and ACUs' if acu_pts else ''} — {SESSION_ID[-8:]}", 18, INK, weight="600")
leg = [("normal", "added this step"), ("tools", "tool search"), ("shrink", "drop: summary / recount (dashed)")]
if glitch: leg.append(("glitch", "anomalous reading (excluded)"))
top1 += legend(54, leg + [("total", "total (right axis)")] + ([("acu", "ACUs (far-right axis)")] if acu_pts else [])) - 54
if acu_pts: amax = nice(max(max(a for _, a in acu_pts), 0.01) * 1.05 / N) * N
for i in range(N + 1):
    y = top1 + h1 - h1 * i / N
    out.append(f'<line x1="{P}" x2="{W-PR}" y1="{y:.1f}" y2="{y:.1f}" stroke="{GRID}"/>')
    text(P - 8, y + 4, k(dmin + dstep * i), 11, anchor="end")
    text(W - PR + 8, y + 4, k(tmax * i / N), 11, INK)
    if acu_pts: text(W - PR + 60, y + 4, f"{amax * i / N:g}", 11, C["acu"])
if dmin < 0: out.append(f'<line x1="{P}" x2="{W-PR}" y1="{yd(0):.1f}" y2="{yd(0):.1f}" stroke="{MUTED}"/>')
text(P - 8, top1 - 12, "Δ tokens", 11, anchor="end"); text(W - PR + 8, top1 - 12, "total", 11, INK)
if acu_pts: text(W - PR + 60, top1 - 12, "ACUs", 11, C["acu"])
n = len(bars); bw = (W - PR - P) / n; pts = []
for j, (idx, tot, dt, kind, raw) in enumerate(bars):
    x = P + j * bw + bw * 0.15; cx = x + bw * 0.35
    if kind == "glitch":
        out.append(f'<line x1="{cx:.1f}" x2="{cx:.1f}" y1="{top1:.1f}" y2="{top1+h1:.1f}" stroke="{C["glitch"]}" stroke-dasharray="4 3"><title>step {idx}: logged {raw:,} tokens (anomalous); {tot:,} used</title></line>')
        text(cx, top1 - 2, f"{raw/1000:.0f}k?", 11, C["glitch"], "middle", "600")
    elif dt < 0:
        out.append(f'<line x1="{cx:.1f}" x2="{cx:.1f}" y1="{top1:.1f}" y2="{top1+h1:.1f}" stroke="{C[kind]}" stroke-width="2" stroke-dasharray="5 3"><title>step {idx}: {dt:+,} tokens (total {tot:,})</title></line>')
        text(cx, top1 - 2, f"{dt/1000:+.1f}k", 11, C[kind], "middle", "600")
    else:
        ya, yb = sorted((yd(0), yd(dt)))
        out.append(f'<rect x="{x:.1f}" y="{ya:.1f}" width="{bw*0.7:.1f}" height="{max(yb-ya, 0.5):.1f}" rx="2" fill="{C[kind]}"><title>step {idx}: {dt:+,} tokens (total {tot:,})</title></rect>')
        if kind != "normal": text(cx, (ya - 6) if dt >= 0 else (yb + 14), f"{dt/1000:+.1f}k", 11, INK, "middle", "600")
    if n <= 25 or j % max(1, n // 20) == 0 or j == n - 1: text(cx, top1 + h1 + 16, idx, 10, anchor="middle")
    pts.append((cx, yt(tot)))
out.append(f'<polyline points="{" ".join(f"{a:.1f},{b:.1f}" for a, b in pts)}" fill="none" stroke="{C["total"]}" stroke-width="2" stroke-linejoin="round"/>')
lx, ly = pts[-1]
out.append(f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="3.5" fill="{C["total"]}"/>')
text(lx - 6, ly - 8, f"{steps[-1][1]:,}", 11, INK, "end", "600")
text(P + 6, top1 + 14, f"start: {steps[0][1]:,} tokens", 11, MUTED)
text((P + W - PR) / 2, top1 + h1 + 36, "Step", 12, anchor="middle")
if acu_pts:
    # Place each ACU reading by time, interpolating between the step positions on the x axis.
    tx = [(ts(events[0]["timestamp"]), float(P))] + [(ts(events[idx - 1]["timestamp"]), cx) for (idx, *_), (cx, _) in zip(bars, pts)]
    if acu_pts[-1][0] > tx[-1][0]: tx.append((acu_pts[-1][0], float(W - PR)))
    def xat(t):
        if t <= tx[0][0]: return tx[0][1]
        for (t0, x0), (t1, x1) in zip(tx, tx[1:]):
            if t <= t1: return x0 + (x1 - x0) * (t - t0) / max(t1 - t0, 1e-9)
        return tx[-1][1]
    ya = lambda a: top1 + h1 * (1 - a / amax)
    ap = [(xat(t), ya(a)) for t, a in acu_pts]
    out.append(f'<polyline points="{" ".join(f"{a:.1f},{b:.1f}" for a, b in ap)}" fill="none" stroke="{C["acu"]}" stroke-width="2" stroke-linejoin="round"/>')
    for j, ((x, y), (t, a)) in enumerate(zip(ap, acu_pts)):
        lab = "total when fetched" if j == len(ap) - 1 and acu_now else "user message"
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="{C["acu"]}"><title>{datetime.fromtimestamp(t, timezone.utc):%H:%M:%S} UTC ({lab}): {a:.2f} ACUs ({a - (acu_pts[j-1][1] if j else 0):+.2f})</title></circle>')
    text(ap[-1][0] - 8, ap[-1][1] + 4, f"{acu_pts[-1][1]:.2f} ACUs", 11, C["acu"], "end", "600")

other_src = {k: v for k, v in src.items() if k not in ("memory_drive", "rules", "sysprompt", "compaction")}
if rules_start: other_src["rules (at start)"] = rules_start
fixed = sorted(((k, v // 4) for k, v in other_src.items()), key=lambda kv: -kv[1])
fixed_total = sum(v for _, v in fixed)
parts = fixed[:4] + ([(f"{len(fixed[4:])} smaller fixed sources", sum(v for _, v in fixed[4:]))] if fixed[4:] else [])
GREYS = ["#64748B", "#94A3B8", "#B4BECB", "#CBD5E1", "#E2E8F0"]
mem, rr, sp, sm = src.get("memory_drive", 0) // 4, repo_rules // 4, src.get("sysprompt", 0) // 4, src.get("compaction", 0) // 4
advice = "" if rr or not repo_used else "Advisory: no AGENTS.md or repo rules loaded. Add an AGENTS.md and repo rules (e.g. .devin/rules/) so the agent gets the repo's conventions."
segs = [("conversation + tool I/O", rest // 4, C["conversation"]), ("tool definitions (est.)", unitemised, C["tooldefs"]),
        ("summary of earlier context", sm, C["summary"]), ("system prompt", sp, C["sysprompt"]), ("memory", mem, C["memory"]), ("AGENTS.md + repo rules", rr, C["reporules"])]
segs = [sg for sg in segs if sg[1] > 0] + [(lab, v, GREYS[j]) for j, (lab, v) in enumerate(parts)]
total = max(sum(v for _, v, _ in segs), 1)
pct = lambda v: "<1%" if 0 < 100 * v / total < 0.5 else f"{100 * v / total:.0f}%"
top2, bh, bwid = top1 + h1 + 90, 44, W - 2 * P
text(P, top2 - 26, f"Context by source at step {li+1} ({T[li]:,} tokens)", 18, INK, weight="600")
x, fx = P, None
for lab, v, col in segs:
    w = bwid * v / total
    out.append(f'<rect x="{x:.1f}" y="{top2}" width="{max(w - 1, 0.5):.1f}" height="{bh}" fill="{col}"><title>{esc(lab)}: {v:,} tokens ({esc(pct(v))})</title></rect>')
    if col not in GREYS:
        if w > 34: text(x + w / 2, top2 + bh / 2 + 4, pct(v), 12, "#FFFFFF", "middle", "600")
    elif fx is None: fx = x
    x += w
if fx is not None and x - fx > 34: text((fx + x) / 2, top2 + bh / 2 + 4, pct(fixed_total), 12, INK, "middle", "600")
rows = [(C["conversation"], "conversation + tool I/O", rest // 4, ""),
        (C["tooldefs"], "tool definitions (estimate, upper bound)", unitemised, ""),
        (C["summary"], "summary of earlier context (compaction)", sm, ""),
        (C["sysprompt"], "system prompt", sp, ""),
        (C["memory"], "memory (memory_drive)", mem, ""),
        (C["reporules"], "AGENTS.md + repo rules (rules loaded after start)", rr, f"  —  {len(loads)} load(s), see table" if loads else ""),
        (None, "fixed overhead", fixed_total, "")] + [(GREYS[j], "    " + lab, v, "") for j, (lab, v) in enumerate(parts)]
rows = [r for r in rows if r[0] != C["summary"] or r[2]]
if advice: rows.insert(next(i for i, r in enumerate(rows) if r[0] == C["reporules"]) + 1, ("ADVICE", advice, 0, ""))
for i, (col, lab, v, extra) in enumerate(rows):
    y = top2 + bh + 28 + i * 22
    if col == "ADVICE": text(P + 18, y, lab, 12, "#B45309", weight="600"); continue
    ind = 16 if lab.startswith("    ") else 0
    if col: out.append(f'<rect x="{P + ind}" y="{y-10}" width="12" height="12" rx="2" fill="{col}"/>')
    text(P + ind + (18 if col else 0), y, f"{lab.strip()}: {v:,} ({pct(v)}){extra}", 12, INK, weight="400" if col else "600")
H = top2 + bh + 28 + len(rows) * 22 + 10
svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
       f'font-family="Inter, -apple-system, Segoe UI, Helvetica, Arial, sans-serif"><rect width="100%" height="100%" fill="#FFFFFF"/>' + "".join(out) + "</svg>")
# Wrapped in HTML: the session sidebar shows a bare SVG as a static image, so <title> tooltips never fire there.
TIP_JS = ("const t=document.getElementById('tip');document.querySelectorAll('svg title').forEach(n=>{const e=n.parentNode,s=n.textContent;n.remove();"
          "e.style.cursor='default';e.addEventListener('mousemove',v=>{t.textContent=s;t.style.display='block';"
          "t.style.left=Math.min(v.clientX+12,innerWidth-t.offsetWidth-4)+'px';t.style.top=(v.clientY+14)+'px'});"
          "e.addEventListener('mouseleave',()=>t.style.display='none')});")
html = (f'<!doctype html><html><head><meta charset="utf-8"><title>Session context — {SESSION_ID[-8:]}</title><style>'
        'body{margin:0;background:#fff}svg{display:block;width:100%;height:auto;max-width:' + str(W) + 'px}'
        '#tip{position:fixed;display:none;pointer-events:none;background:#0F172A;color:#fff;font:12px Inter,-apple-system,Segoe UI,Helvetica,Arial,sans-serif;'
        'padding:4px 8px;border-radius:4px;white-space:nowrap;z-index:9}</style></head><body>'
        + svg + f'<div id="tip"></div><script>{TIP_JS}</script></body></html>')
path = f"{OUT}/session-context-{SID}.html"
open(path, "w").write(html)
print(f"\nChart written to {path}")
open(f"{OUT}/session-context-{SID}.md", "w").write("\n".join(_full) + "\n")

# Keep only the KEEP most recently analysed sessions so repeated runs can't fill the disk.
groups = {}
for f in os.listdir(OUT):
    if f.startswith("session-context-"):
        fp = os.path.join(OUT, f); g = groups.setdefault(f.removeprefix("session-context-").split(".")[0], [])
        g.append((os.path.getmtime(fp), fp))
for sid, files in sorted(groups.items(), key=lambda kv: -max(m for m, _ in kv[1]))[KEEP:]:
    for _, fp in files: os.remove(fp)
