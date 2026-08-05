from __future__ import annotations

import html
import json
from typing import Any

_STYLE = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin: 0; background: #0a0c0a; color: #e6e6d4; font-family: system-ui, -apple-system, "Segoe UI", sans-serif; line-height: 1.5; }
main { max-width: 960px; margin: 0 auto; padding: 24px 16px 64px; }
header.top { border-bottom: 1px solid #262a26; padding-bottom: 16px; margin-bottom: 24px; }
h1 { font-size: 20px; margin: 0 0 8px; }
h2 { font-size: 16px; margin: 0 0 12px; }
section { background: #121512; border: 1px solid #262a26; border-radius: 10px; padding: 16px; margin-bottom: 16px; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #1e221e; vertical-align: top; }
th { color: #9aa08a; font-weight: 600; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 12px; background: #1e221e; margin-right: 6px; }
.badge--warn { background: #3d2f1a; color: #e8c46a; }
pre { white-space: pre-wrap; word-break: break-all; background: #0d100d; border: 1px solid #1e221e; border-radius: 6px; padding: 10px; font-size: 12px; font-family: ui-monospace, "SF Mono", Consolas, monospace; }
.dl { display: block; white-space: pre-wrap; font-family: ui-monospace, "SF Mono", Consolas, monospace; font-size: 12px; padding: 0 8px; }
.dl-add { background: rgba(74, 148, 74, 0.18); color: #9fd49f; }
.dl-del { background: rgba(200, 74, 74, 0.18); color: #e0a0a0; }
.dl-ctx { color: #9aa08a; }
details { margin-bottom: 8px; }
summary { cursor: pointer; font-size: 13px; color: #c9ccb8; }
.meta { color: #9aa08a; font-size: 12px; }
"""

_JS = """
document.querySelectorAll("details").forEach((d) => { d.open = false; });
"""


def _esc(value: Any) -> str:
    return html.escape(str(value))


def _classify_diff_line(line: str) -> str:
    if line.startswith("@@") or line.startswith("diff --git"):
        return "dl-hunk"
    if line.startswith("+") and not line.startswith("+++"):
        return "dl-add"
    if line.startswith("-") and not line.startswith("---"):
        return "dl-del"
    return "dl-ctx"


def _render_diffs(diffs: list[dict[str, Any]]) -> str:
    if not diffs:
        return '<div class="meta">No repository changes recorded.</div>'
    blocks: list[str] = []
    for diff in diffs:
        lines = "".join(
            f'<span class="dl {_classify_diff_line(line)}">{_esc(line)}</span>\n'
            for line in diff["diff_text"].splitlines()
        )
        status = _esc(diff.get("status_text", "")).strip()
        blocks.append(
            "<details open>"
            f"<summary>{_esc(diff['repo'])} "
            f'<span class="badge">+{diff["added_lines"]} -{diff["removed_lines"]} '
            f"{diff['file_count']} files</span></summary>"
            f'<pre class="meta" style="margin-bottom:8px">{status}</pre>'
            f"<div>{lines}</div>"
            "</details>"
        )
    return "\n".join(blocks)


def _render_events(events: list[dict[str, Any]]) -> str:
    if not events:
        return '<div class="meta">No events recorded.</div>'
    groups: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        groups.setdefault(str(event.get("kind", "unknown")), []).append(event)
    rows: list[str] = []
    for kind in sorted(groups):
        rows.append(f"<details><summary>{_esc(kind)} ({len(groups[kind])})</summary>")
        rows.append("<table><tr><th>#</th><th>Payload</th></tr>")
        for idx, event in enumerate(groups[kind], start=1):
            payload = {k: v for k, v in event.items() if k not in {"sequence", "kind", "created_at"}}
            rows.append(f"<tr><td>{idx}</td><td><pre>{_esc(json.dumps(payload, ensure_ascii=False))}</pre></td></tr>")
        rows.append("</table></details>")
    return "\n".join(rows)


def render_report_html(payload: dict[str, Any]) -> str:
    run = payload.get("run", {})
    scorecard = payload.get("scorecard", {}) or {}
    outcome = scorecard.get("outcome", {}) or {}
    telemetry = payload.get("telemetry", {}) or {}
    events = telemetry.get("events", [])
    graph = payload.get("graph", {}) or {}
    budget = payload.get("budget_adjustments", {}) or {}
    turns = payload.get("turn_summary", {}) or {}

    model = run.get("model", {}) or {}
    badges = [
        f'<span class="badge">{_esc(run.get("status", ""))}</span>',
    ]
    if outcome.get("censored"):
        badges.append('<span class="badge badge--warn">censored</span>')

    score_rows = "".join(
        f"<tr><td>{_esc(dim.get('name', ''))}</td><td>{_esc(dim.get('points', ''))}</td>"
        f"<td>{_esc(dim.get('maximum', ''))}</td></tr>"
        for dim in (scorecard.get("dimensions") or [])
    )
    overtime = scorecard.get("overtime_penalty") or {}
    ot_rows = "".join(
        f"<tr><td>{_esc(name)}</td><td>{_esc(dim.get('overrun', 0))}</td><td>{_esc(dim.get('penalty', 0))}</td></tr>"
        for name, dim in sorted((overtime.get("dimensions") or {}).items())
    )
    overview_rows = (
        f"<tr><th>Model</th><td>{_esc(model.get('name', '—'))} ({_esc(model.get('model_id', '—'))})</td></tr>"
        f"<tr><th>Scenario</th><td>{_esc(run.get('scenario', '—'))}</td></tr>"
        f"<tr><th>Status</th><td>{_esc(run.get('status', '—'))}</td></tr>"
        f"<tr><th>Started</th><td>{_esc(run.get('started_at') or '—')}</td></tr>"
        f"<tr><th>Completed</th><td>{_esc(run.get('completed_at') or '—')}</td></tr>"
        f"<tr><th>Turns</th><td>{_esc(turns.get('total_turns', '—'))}</td></tr>"
        f"<tr><th>Score</th><td>{_esc(scorecard.get('score', '—'))} / {_esc(scorecard.get('maximum', '—'))}</td></tr>"
    )
    graph_rows = "".join(
        f"<tr><td>{_esc(h.get('id', ''))}</td><td>{_esc(h.get('text', ''))}</td></tr>"
        for h in (graph.get("hypotheses") or [])
    )
    evidence_rows = "".join(
        f"<tr><td>{_esc(e.get('id', ''))}</td><td>{_esc(e.get('text', ''))}</td></tr>"
        for e in (graph.get("evidence") or [])
    )
    link_rows = "".join(
        f"<tr><td>{_esc(link.get('hypothesis_id', ''))}</td><td>{_esc(link.get('evidence_id', ''))}</td></tr>"
        for link in (graph.get("links") or [])
    )
    budget_fields = "、".join(_esc(f) for f in (budget.get("fields") or []))
    budget_detail = (
        f"{budget.get('count', 0)} 次调整 · 字段：{budget_fields or '—'}"
        f" · 首次 {_esc(budget.get('first_at') or '—')} · 末次 {_esc(budget.get('last_at') or '—')}"
    )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(run.get("scenario", "run"))} · 运行报告</title>
<style>{_STYLE}</style>
</head>
<body>
<main>
<header class="top">
<h1>{_esc(model.get("name", ""))} · {_esc(run.get("scenario", ""))}</h1>
<div class="meta">{_esc(run.get("id", ""))}</div>
<div>{"".join(badges)}</div>
<div class="meta" style="margin-top:8px">
{_esc(run.get("started_at", ""))} → {_esc(run.get("completed_at", ""))}
</div>
</header>

<section id="scorecard">
<h2>Scorecard</h2>
<table><tr><th>Dimension</th><th>Points</th><th>Maximum</th></tr>{score_rows}</table>
<div class="meta" style="margin-top:8px">
Score <strong>{_esc(scorecard.get("score", ""))}</strong> / {_esc(scorecard.get("maximum", ""))}
</div>
{overtime and f'<div class="meta" id="overtime_penalty">Overtime penalty: {_esc(overtime.get("total_penalty", 0))}</div><table><tr><th>Dimension</th><th>Overrun</th><th>Penalty</th></tr>{ot_rows}</table>' or ""}
</section>

<section id="overview">
<h2>Overview</h2>
<table>{overview_rows}</table>
</section>

<section id="graph">
<h2>Hypothesis graph</h2>
<table><tr><th>Hypothesis</th><th>Text</th></tr>{graph_rows or '<tr><td colspan="2" class="meta">None</td></tr>'}</table>
<table style="margin-top:8px"><tr><th>Evidence</th><th>Text</th></tr>{evidence_rows or '<tr><td colspan="2" class="meta">None</td></tr>'}</table>
<table style="margin-top:8px"><tr><th>Hypothesis</th><th>Evidence</th></tr>{link_rows or '<tr><td colspan="2" class="meta">None</td></tr>'}</table>
</section>

<section id="audit">
<h2>Audit trail</h2>
{_render_events(events)}
</section>

<section id="diffs">
<h2>Repository changes</h2>
{_render_diffs(payload.get("diffs") or [])}
</section>

<section id="telemetry">
<h2>Telemetry</h2>
<div class="meta">Turns: {_esc(turns.get("total_turns", "—"))} completed {_esc(turns.get("completed_turns", "—"))} · avg {_esc(turns.get("average_duration_ms", "—"))} ms · max {_esc(turns.get("max_duration_ms", "—"))} ms</div>
<div class="meta" style="margin-top:4px">Budget adjustments: {budget_detail}</div>
</section>

<script>{_JS}</script>
</main>
</body>
</html>
"""


def json_payload_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return events
