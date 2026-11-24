"""Analyse a saved session-context JSON (written by the fetch step in SKILL.md).

Usage: python3 analyze.py <session-id>
Prints Markdown tables (step table trimmed to notable steps for long sessions),
writes the full report and the chart (session-context-<id>.md / .html, an SVG chart wrapped in HTML with hover tooltips) to ~/.cache/session-context/,
keeping files for only the KEEP most recently analysed sessions.
"""
import json, math, os, sys
from datetime import datetime, timezone
from html import escape as esc

def ts(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def utc_time(timestamp, fmt="%Y-%m-%d %H:%M:%S"):
    return datetime.fromtimestamp(timestamp, timezone.utc).strftime(fmt)


def byte_share(size, total):
    percent = 100 * size / max(1, total)
    return "<1%" if 0 < percent < 0.5 else f"{percent:.0f}%"


SESSION_ID = sys.argv[1] if sys.argv[1].startswith("devin-") else "devin-" + sys.argv[1]
SID = SESSION_ID.removeprefix("devin-")
OUT, KEEP = os.path.expanduser("~/.cache/session-context"), 5
with open(f"{OUT}/session-context-{SID}.json", encoding="utf-8") as capture:
    data = json.load(capture)
events = sorted(data["events"], key=lambda e: ts(e["timestamp"]))
if not events:
    print("No context_growth_update events for this session."); sys.exit()

_full = []
def print(s="", brief=True):
    _full.append(str(s))
    if brief: sys.stdout.write(str(s) + "\n")

acus = data.get("acus")
print(f"Session {SESSION_ID}: {len(events)} context snapshots")

T = [e["current_context_tokens"] for e in events]
B = [e["current_context_bytes"] for e in events]
n_ev = len(events)
# Flag an isolated spike that nearly reverts while bytes stay steady or grow.
suspect = set()
for i in range(1, n_ev - 1):
    up, db = T[i] - T[i-1], B[i] - B[i-1]
    if up > 10000 and up > 3 * max(db, 0) / 4 and B[i+1] >= B[i] >= B[i-1] and abs(T[i+1] - T[i-1]) <= 0.2 * up:
        suspect.add(i)

def calls(e): return {a["tool_name"] + (f":{a['action']}" if a.get("action") else ""): a["call_count"] for a in e.get("tool_aggregates", [])}
print("\n| Step | Time (UTC) | Logged tokens | Δ tokens | Bytes | Δ bytes | Tools called | Note |\n|---|---|---|---|---|---|---|---|")
steps, prev_calls, searched = [], {}, []
notable_delta = max(2000, 0.05 * max(T))
for i, e in enumerate(events):
    c = calls(e)
    newc = {k: v - prev_calls.get(k, 0) for k, v in c.items() if v > prev_calls.get(k, 0)}
    prev_calls = c
    searched.append(any("tool_search" in k for k in newc))
    dt = T[i] - T[i-1] if i else 0
    db = B[i] - B[i-1] if i else 0
    kind, note = "normal", ""
    if i in suspect:
        kind, note = "suspect", "possible anomalous reading: isolated token spike"
    elif dt < 0:
        kind, note = "drop", "tokens and bytes fell" if db < 0 else "tokens fell; bytes stayed flat or grew"
    elif i and dt > 2000 and dt > 2 * max(db, 0) / 4:
        if searched[i] or searched[i-1]: kind, note = "tools", "tokens outpaced bytes/4; tool search nearby"
        else: note = "tokens grew faster than bytes/4"
    if i - 1 in suspect: note = (note + "; " if note else "") + "Δ follows a flagged reading"
    steps.append((i + 1, T[i], dt, kind))
    notable = n_ev <= 30 or i in (0, n_ev - 1) or bool(note) or abs(dt) >= notable_delta
    print(f"| {i+1} | {utc_time(ts(e['timestamp']), '%H:%M:%S')} | {T[i]:,} | {dt:+,} | {B[i]:,} | {db:+,} | {', '.join(f'{k}×{v}' for k, v in newc.items())} | {note} |", brief=notable)
if n_ev > 30: print(f"\n(Only notable steps shown; all {n_ev} steps are in {OUT}/session-context-{SID}.md.)")
acu_pts = sorted(((ts(t), a) for t, a in data.get("acu_points", [])), key=lambda point: point[0])
acu_total = (ts(data["fetched_at"]), acus) if acus is not None and data.get("fetched_at") else None
acu_deltas = [None] if acu_pts else []
for (_, previous), (_, current) in zip(acu_pts, acu_pts[1:]):
    acu_deltas.append(current - previous if current >= previous else None)

if acu_pts:
    print(f"\nHistorical ACU readings ({len(acu_pts)}). Deltas compare consecutive historical readings and are unavailable if the total decreases.")
    print("\n| Time (UTC) | ACUs | Δ ACUs |\n|---|---|---|", brief=len(acu_pts) <= 20)
    for (t, a), delta in zip(acu_pts, acu_deltas):
        change = f"{delta:+.2f}" if delta is not None else "—"
        print(f"| {utc_time(t)} | {a:.2f} | {change} |", brief=len(acu_pts) <= 20)
    if len(acu_pts) > 20:
        print("See the chart for individual readings.")
if acus is not None:
    fetched = f" at {utc_time(acu_total[0])} UTC" if acu_total else ""
    print(f"\nSession ACU total when fetched{fetched}: {acus:.2f}.")
if suspect:
    print(f"\nPossible anomalous token readings at step(s) {', '.join(str(i+1) for i in sorted(suspect))}. Logged values and deltas are shown.")

last = events[-1]
src = last.get("per_source_context_bytes", {})
named_bytes = sum(src.values())
rest = B[-1] - named_bytes
other_context = "Other context (e.g. conversation and tool activity)"
gap = round(T[-1] - B[-1] / 4)
print(f"\nContext byte breakdown at step {n_ev} ({B[-1]:,} bytes):\n\n| Source | Bytes | Share of context bytes |\n|---|---|---|")
for k, v in sorted(src.items(), key=lambda kv: -kv[1]):
    share = byte_share(v, B[-1]) if rest >= 0 else "—"
    print(f"| {k} | {v:,} | {share} |")
if rest > 0:
    print(f"| {other_context} | {rest:,} | {byte_share(rest, B[-1])} |")
    print("\nOther context is the byte remainder after subtracting named sources.")
elif rest < 0:
    print(f"\nNamed source bytes exceed total context bytes by {-rest:,}.")
print(f"\nByte-to-token estimate difference (logged tokens − bytes/4): first {T[0] - B[0] / 4:+,.0f}, step {n_ev} {gap:+,}.")

rule_sizes = [e.get("per_source_context_bytes", {}).get("rules", 0) for e in events]
rule_changes = [(i + 1, current, current - previous)
                for i, (previous, current) in enumerate(zip(rule_sizes, rule_sizes[1:]), 1) if current != previous]
if rule_changes:
    print("\nChanges to aggregate rules bytes:\n\n| Step | Rules bytes | Δ rules bytes |\n|---|---|---|")
    for step, size, delta in rule_changes:
        print(f"| {step} | {size:,} | {delta:+,} |")
print("\n| Tool | Calls | Output bytes | ≈Tokens |\n|---|---|---|---|")
for a in sorted(events[-1].get("tool_aggregates", []), key=lambda a: -a["total_output_bytes"]):
    name = a["tool_name"] + (f":{a['action']}" if a.get("action") else "")
    print(f"| {name} | {a['call_count']} | {a['total_output_bytes']:,} | {a.get('approx_ant_tokens', a['total_output_bytes']//4):,} |")

# ---- SVG chart (pure Python) ----
def nice(v):
    m = 10 ** math.floor(math.log10(max(v, 1)))
    return next(f * m for f in (1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10) if f * m >= v)

C = {"total": "#0F172A", "normal": "#6366F1", "tools": "#F59E0B", "drop": "#10B981", "suspect": "#EF4444",
     "other": "#0EA5E9", "memory": "#D946EF", "rules": "#0F766E", "sysprompt": "#334155", "summary": "#10B981",
     "acu": "#DB2777", "acu_total": "#9D174D"}
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

acu_axis_points = acu_pts + ([acu_total] if acu_total else [])
h1, top1, PR = 300, 70, (130 if acu_axis_points else 70)
def k(v): return f"{v/1000:g}k" if v else "0"
bars = steps[1:] or steps
# The per-step axis starts at 0; drops are drawn as labelled dashed markers.
d = [max(b[2], 0) for b in bars]
hi, lo = max(max(d), 1) * 1.1, 0
dstep = nice((hi - lo) / 5)
dmin, dmax = math.floor(lo / dstep) * dstep, math.ceil(hi / dstep) * dstep
N = round((dmax - dmin) / dstep)
tmax = nice(max(s[1] for s in steps) * 1.05 / N) * N
yd = lambda v: top1 + h1 * (dmax - v) / (dmax - dmin)
yt = lambda v: top1 + h1 * (1 - v / tmax)
text(P, 32, f"Logged context tokens{' and ACUs' if acu_axis_points else ''} — {SESSION_ID[-8:]}", 18, INK, weight="600")
leg = [("normal", "added this step"), ("tools", "tool search nearby"), ("drop", "token drop (dashed)"), ("total", "logged total")]
if suspect: leg.append(("suspect", "possible anomalous reading"))
if acu_pts: leg.append(("acu", "historical ACUs"))
if acu_total: leg.append(("acu_total", "ACU total when fetched (diamond)"))
top1 += legend(54, leg) - 54
if acu_axis_points: amax = nice(max(max(a for _, a in acu_axis_points), 0.01) * 1.05 / N) * N
for i in range(N + 1):
    y = top1 + h1 - h1 * i / N
    out.append(f'<line x1="{P}" x2="{W-PR}" y1="{y:.1f}" y2="{y:.1f}" stroke="{GRID}"/>')
    text(P - 8, y + 4, k(dmin + dstep * i), 11, anchor="end")
    text(W - PR + 8, y + 4, k(tmax * i / N), 11, INK)
    if acu_axis_points: text(W - PR + 60, y + 4, f"{amax * i / N:g}", 11, C["acu"])
text(P - 8, top1 - 12, "Δ tokens", 11, anchor="end"); text(W - PR + 8, top1 - 12, "total", 11, INK)
if acu_axis_points: text(W - PR + 60, top1 - 12, "ACUs", 11, C["acu"])
n = len(bars); bw = (W - PR - P) / n; pts = []
for j, (idx, tot, dt, kind) in enumerate(bars):
    x = P + j * bw + bw * 0.15; cx = x + bw * 0.35
    label = f"step {idx}: {dt:+,} tokens (logged total {tot:,})"
    if dt < 0:
        out.append(f'<line x1="{cx:.1f}" x2="{cx:.1f}" y1="{top1:.1f}" y2="{top1+h1:.1f}" stroke="{C[kind]}" stroke-width="2" stroke-dasharray="5 3"><title>{label}</title></line>')
        text(cx, top1 - 2, f"{dt/1000:+.1f}k", 11, C[kind], "middle", "600")
    else:
        ya, yb = sorted((yd(0), yd(dt)))
        if kind == "suspect": label += " · possible anomalous reading"
        if kind == "tools": label += " · tool search nearby"
        out.append(f'<rect x="{x:.1f}" y="{ya:.1f}" width="{max(bw*0.7, 0.1):.1f}" height="{max(yb-ya, 0.5):.1f}" rx="2" fill="{C[kind]}"><title>{label}</title></rect>')
        if kind != "normal": text(cx, ya - 6, f"{dt/1000:+.1f}k", 11, C[kind], "middle", "600")
    if n <= 25 or j % max(1, n // 20) == 0 or j == n - 1: text(cx, top1 + h1 + 16, idx, 10, anchor="middle")
    pts.append((cx, yt(tot)))
out.append(f'<polyline points="{" ".join(f"{a:.1f},{b:.1f}" for a, b in pts)}" fill="none" stroke="{C["total"]}" stroke-width="2" stroke-linejoin="round"/>')
lx, ly = pts[-1]
out.append(f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="3.5" fill="{C["total"]}"/>')
text(lx - 6, ly - 8, f"{steps[-1][1]:,}", 11, INK, "end", "600")
text(P + 6, top1 + 14, f"start: {steps[0][1]:,} tokens", 11, MUTED)
text((P + W - PR) / 2, top1 + h1 + 36, "Step", 12, anchor="middle")
if acu_axis_points:
    # Place each ACU reading by time, interpolating between the step positions on the x axis.
    tx = [(ts(events[0]["timestamp"]), float(P))] + [(ts(events[idx - 1]["timestamp"]), cx) for (idx, *_), (cx, _) in zip(bars, pts)]
    latest_acu_time = max(t for t, _ in acu_axis_points)
    if latest_acu_time > tx[-1][0]: tx.append((latest_acu_time, float(W - PR)))
    def xat(t):
        if t <= tx[0][0]: return tx[0][1]
        for (t0, x0), (t1, x1) in zip(tx, tx[1:]):
            if t <= t1: return x0 + (x1 - x0) * (t - t0) / max(t1 - t0, 1e-9)
        return tx[-1][1]
    ya = lambda a: top1 + h1 * (1 - a / amax)
    historical_positions = [(xat(t), ya(a)) for t, a in acu_pts]
    if historical_positions:
        out.append(f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in historical_positions)}" fill="none" stroke="{C["acu"]}" stroke-width="2" stroke-linejoin="round"/>')
    for (x, y), (t, amount), delta in zip(historical_positions, acu_pts, acu_deltas):
        change = f" ({delta:+.2f} since prior reading)" if delta is not None else ""
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="{C["acu"]}"><title>{utc_time(t)} UTC: {amount:.2f} ACUs{change}</title></circle>')
    if acu_total:
        t, amount = acu_total
        x, y = xat(t), ya(amount)
        out.append(f'<path d="M {x:.1f},{y-4:.1f} l 4,4 -4,4 -4,-4 z" fill="{C["acu_total"]}"><title>{utc_time(t)} UTC: {amount:.2f} ACUs (session total when fetched)</title></path>')
        text(x - 8, y + 4, f"{amount:.2f} ACUs", 11, C["acu_total"], "end", "600")

other_named = sorted(((k, v) for k, v in src.items() if k not in ("memory_drive", "rules", "sysprompt", "compaction")),
                     key=lambda kv: -kv[1])
other_total = sum(v for _, v in other_named)
parts = other_named[:4]
if len(other_named) > 4:
    parts.append((f"{len(other_named) - 4} smaller sources", sum(v for _, v in other_named[4:])))
GREYS = ["#64748B", "#94A3B8", "#B4BECB", "#CBD5E1", "#E2E8F0"]
mem, rules, sp, sm = (src.get(key, 0) for key in ("memory_drive", "rules", "sysprompt", "compaction"))
source_rows = [(other_context, max(rest, 0), C["other"]),
               ("summary of earlier context (compaction)", sm, C["summary"]), ("system prompt", sp, C["sysprompt"]),
               ("memory", mem, C["memory"]), ("rules (all sources)", rules, C["rules"])]
segs = [row for row in source_rows if row[1] > 0]
segs += [(lab, v, GREYS[j]) for j, (lab, v) in enumerate(parts) if v > 0]
total = max(1, B[-1], named_bytes)
top2, bh, bwid = top1 + h1 + 90, 44, W - 2 * P
text(P, top2 - 32, f"Context bytes by source at step {n_ev}", 18, INK, weight="600")
caption = f"{B[-1]:,} total context bytes"
if rest < 0:
    caption += f". Named sources sum to {named_bytes:,} bytes. Shares use that sum."
elif rest > 0:
    caption += ". Other context is the remainder after subtracting named sources."
text(P, top2 - 12, caption)
x, fx = P, None
for lab, v, col in segs:
    w = bwid * v / total
    share = byte_share(v, total)
    out.append(f'<rect x="{x:.1f}" y="{top2}" width="{max(w - 1, 0.5):.1f}" height="{bh}" fill="{col}"><title>{esc(lab)}: {v:,} bytes ({esc(share)})</title></rect>')
    if col not in GREYS:
        if w > 34: text(x + w / 2, top2 + bh / 2 + 4, share, 12, "#FFFFFF", "middle", "600")
    elif fx is None: fx = x
    x += w
if fx is not None and x - fx > 34: text((fx + x) / 2, top2 + bh / 2 + 4, byte_share(other_total, total), 12, INK, "middle", "600")
rows = [(col, lab, v) for lab, v, col in source_rows if v > 0]
if other_total:
    rows += [(None, "Other named sources", other_total)]
    rows += [(GREYS[j], "    " + lab, v) for j, (lab, v) in enumerate(parts) if v > 0]
for i, (col, lab, v) in enumerate(rows):
    y = top2 + bh + 28 + i * 22
    ind = 16 if lab.startswith("    ") else 0
    if col: out.append(f'<rect x="{P + ind}" y="{y-10}" width="12" height="12" rx="2" fill="{col}"/>')
    value = f"{v:,} bytes ({byte_share(v, total)})"
    text(P + ind + (18 if col else 0), y, f"{lab.strip()}: {value}", 12, INK, weight="400" if col else "600")
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
with open(path, "w", encoding="utf-8") as chart:
    chart.write(html)
print(f"\nChart written to {path}")
with open(f"{OUT}/session-context-{SID}.md", "w", encoding="utf-8") as report:
    report.write("\n".join(_full) + "\n")

# Keep only the KEEP most recently analysed sessions so repeated runs can't fill the disk.
groups = {}
for f in os.listdir(OUT):
    if f.startswith("session-context-"):
        fp = os.path.join(OUT, f); g = groups.setdefault(f.removeprefix("session-context-").split(".")[0], [])
        g.append((os.path.getmtime(fp), fp))
for sid, files in sorted(groups.items(), key=lambda kv: -max(m for m, _ in kv[1]))[KEEP:]:
    for _, fp in files: os.remove(fp)
