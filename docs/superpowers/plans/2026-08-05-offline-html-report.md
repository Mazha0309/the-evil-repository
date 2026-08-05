# 离线 HTML 报告 实现计划（v0.14.0 追加）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 运行详情页的完整静态内容生成自包含 HTML 报告，打进归档（tar.gz 含 report.html），导出中心支持第 3 种格式（HTML），离线打开直接可看。

**Architecture:** worker 归档时渲染 `report.html` 存进 tar.gz（数据齐全：scorecard/事件/图谱/diff）；`GET /runs/{id}/export?format=html` 优先从归档提取，缺失时动态渲染兜底；渲染模块 `report_html.py` 复用 reports payload 构造，零外部依赖（内联 CSS + 系统字体 + 少量内联 JS），深色卡片风与详情页一致。

**Tech Stack:** Python 3.13 / FastAPI / pytest（后端）；React 18 / vitest（前端）。

**Spec:** `docs/superpowers/specs/2026-08-05-budget-harness-diff-archive-design.md` §7.1

---

### Task 1: `report_html.py` 渲染模块

**Files:**
- Create: `apps/api/app/report_html.py`
- Test: `apps/api/tests/test_report_html.py`

- [ ] **Step 1: 写失败测试**

创建 `apps/api/tests/test_report_html.py`：

```python
import json

from app.report_html import render_report_html


def _payload() -> dict:
    return {
        "run": {
            "id": "run-1",
            "model": {"name": "Test Model", "model_id": "test-model"},
            "scenario": "terminal-repository",
            "status": "evaluated",
            "started_at": "2026-08-05T00:00:00Z",
            "completed_at": "2026-08-05T00:30:00Z",
            "censored": False,
        },
        "scorecard": {
            "score": 900,
            "maximum": 1200,
            "dimensions": [{"name": "efficiency", "points": 300, "maximum": 300}],
            "overtime_penalty": {"total_penalty": 0},
            "outcome": {"status": "evaluated", "censored": False},
        },
        "telemetry": {"summary": {"turns": 5}, "events": []},
        "diffs": [
            {
                "repo": "dead-letter",
                "diff_text": "diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n@@ -1,1 +1,2 @@\n- old\n+ new\n",
                "status_text": " M README.md",
                "added_lines": 1,
                "removed_lines": 1,
                "file_count": 1,
            }
        ],
        "graph": {
            "hypotheses": [{"id": "h1", "text": "X caused Y"}],
            "evidence": [{"id": "e1", "text": "log shows X"}],
            "links": [{"hypothesis_id": "h1", "evidence_id": "e1"}],
        },
        "budget_adjustments": {"count": 1, "first_at": "2026-08-05T00:10:00Z", "last_at": "2026-08-05T00:10:00Z", "fields": ["hard_tool_calls"]},
        "turn_summary": {"total_turns": 5, "completed_turns": 5, "average_duration_ms": 100, "max_duration_ms": 200},
    }


def test_html_is_self_contained() -> None:
    html = render_report_html(_payload())
    assert html.startswith("<!doctype html>")
    assert "<style>" in html
    assert "https://" not in html  # 零外部依赖
    assert "http://" not in html


def test_html_contains_all_sections() -> None:
    html = render_report_html(_payload())
    for marker in (
        "scorecard", "overview", "graph", "audit", "diffs", "telemetry",
        "overtime_penalty", "hard_tool_calls", "dead-letter", "README.md",
    ):
        assert marker in html


def test_html_diff_lines_are_classified() -> None:
    html = render_report_html(_payload())
    assert 'class="dl dl-add"' in html
    assert 'class="dl dl-del"' in html


def test_html_escapes_content() -> None:
    payload = _payload()
    payload["scorecard"] = {"score": 900, "maximum": 1200, "dimensions": [], "outcome": {"status": "evaluated", "censored": False}}
    payload["diffs"] = [{"repo": '<script>', "diff_text": "<script>alert(1)</script>", "status_text": "", "added_lines": 0, "removed_lines": 0, "file_count": 0}]
    html = render_report_html(payload)
    assert "<script>alert(1)</script>" not in html
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_report_html.py -v`
Expected: FAIL（ImportError）

- [ ] **Step 3: 实现 `apps/api/app/report_html.py`**

```python
from __future__ import annotations

import html
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
            f'{diff["file_count"]} files</span></summary>'
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
        f"<tr><td>{_esc(name)}</td><td>{_esc(dim.get('overrun', 0))}</td>"
        f"<td>{_esc(dim.get('penalty', 0))}</td></tr>"
        for name, dim in sorted((overtime.get("dimensions") or {}).items())
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
        f"<tr><td>{_esc(link.get('hypothesis_id', ''))}</td>"
        f"<td>{_esc(link.get('evidence_id', ''))}</td></tr>"
        for link in (graph.get("links") or [])
    )
    budget_fields = "、".join(_esc(f) for f in (budget.get("fields") or []))
    budget_detail = (
        f'{budget.get("count", 0)} 次调整 · 字段：{budget_fields or "—"}'
        f" · 首次 {_esc(budget.get('first_at') or '—')} · 末次 {_esc(budget.get('last_at') or '—')}"
    )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(run.get('scenario', 'run'))} · 运行报告</title>
<style>{_STYLE}</style>
</head>
<body>
<main>
<header class="top">
<h1>{_esc(model.get('name', ''))} · {_esc(run.get('scenario', ''))}</h1>
<div class="meta">{_esc(run.get('id', ''))}</div>
<div>{''.join(badges)}</div>
<div class="meta" style="margin-top:8px">
{_esc(run.get('started_at', ''))} → {_esc(run.get('completed_at', ''))}
</div>
</header>

<section>
<h2>Scorecard</h2>
<table><tr><th>Dimension</th><th>Points</th><th>Maximum</th></tr>{score_rows}</table>
<div class="meta" style="margin-top:8px">
Score <strong>{_esc(scorecard.get('score', ''))}</strong> / {_esc(scorecard.get('maximum', ''))}
</div>
{overtime and f'<div class="meta">Overtime penalty: {_esc(overtime.get("total_penalty", 0))}</div><table><tr><th>Dimension</th><th>Overrun</th><th>Penalty</th></tr>{ot_rows}</table>' or ''}
</section>

<section>
<h2>Hypothesis graph</h2>
<table><tr><th>Hypothesis</th><th>Text</th></tr>{graph_rows or '<tr><td colspan="2" class="meta">None</td></tr>'}</table>
<table style="margin-top:8px"><tr><th>Evidence</th><th>Text</th></tr>{evidence_rows or '<tr><td colspan="2" class="meta">None</td></tr>'}</table>
<table style="margin-top:8px"><tr><th>Hypothesis</th><th>Evidence</th></tr>{link_rows or '<tr><td colspan="2" class="meta">None</td></tr>'}</table>
</section>

<section>
<h2>Audit trail</h2>
{_render_events(events)}
</section>

<section>
<h2>Repository changes</h2>
{_render_diffs(payload.get("diffs") or [])}
</section>

<section>
<h2>Telemetry</h2>
<div class="meta">Turns: {_esc(turns.get('total_turns', '—'))} completed {_esc(turns.get('completed_turns', '—'))} · avg {_esc(turns.get('average_duration_ms', '—'))} ms · max {_esc(turns.get('max_duration_ms', '—'))} ms</div>
<div class="meta" style="margin-top:4px">Budget adjustments: {budget_detail}</div>
</section>

<script>{_JS}</script>
</main>
</body>
</html>
"""


def json_payload_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return events
```

（注意：`import json` 顶部补上；`_JS` 里 details 默认折叠——但测试 `test_html_diff_lines_are_classified` 依赖 class 而非 open 状态，`details open` 用于 diff 保持展开。）

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_report_html.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add apps/api/app/report_html.py apps/api/tests/test_report_html.py
git commit -m "feat: offline HTML report renderer"
```

### Task 2: worker 归档集成（tar.gz 含 report.html）

**Files:**
- Modify: `apps/api/app/scenario/sdk.py`（`archive`）
- Modify: `apps/api/app/worker.py`（`complete`/归档调用处）
- Test: `apps/api/tests/test_run_archival.py`、`apps/api/tests/test_worker.py`

- [ ] **Step 1: 写失败测试**

在 `apps/api/tests/test_run_archival.py` 末尾追加（复用该文件现有归档测试的构造，若该文件无 fixture 则用 test_scenario_sdk.py 方式——参考 Task 13 的做法）：

```python
def test_archive_contains_report_html(<现有构造>) -> None:
    # 构造 PreparedScenario + result（含 scorecard 的 artifacts）
    # sdk.archive(prepared, result, destination)
    # 打开 tar.gz：run.json["archive_schema_version"] >= 3 且存在 report.html 成员，
    # report.html 内容以 "<!doctype html>" 开头
```

- [ ] **Step 2: 运行确认 FAIL**

- [ ] **Step 3: 实现**

3a. `sdk.py` `archive()` 签名加 `report_html: str | None = None` 参数；`detailed_payloads` 增加：

```python
        if report_html is not None:
            detailed_payloads["report.html"] = report_html.encode("utf-8")
```

（注意 `detailed_payloads` 的值形态：看现有代码是 str 还是 bytes——`jsonl_bytes`/`json_bytes` 返回 bytes；report_html 按 bytes 加。`archive_readme` 加 "report.html  Offline self-contained HTML report" 行。）

3b. `worker.py` 归档调用处（`complete()` 里 `archive(...)` 调用点）：在调用前构造 payload 并渲染：

```python
                from app.api.reports import _report_payload
                from app.report_html import render_report_html

                report_payload = _report_payload(run_id, include="full-events")
                # 事件用完整版；diffs 从 result.artifacts 填充（worker 阶段归档未生成）
                diffs = []
                for key in ("dead-letter.diff", "palimpsest.diff"):
                    text = result.artifacts.get(key, "")
                    if text:
                        from app.api.diffs import _stats
                        diffs.append({
                            "repo": key.rsplit(".", 1)[0],
                            "diff_text": text,
                            "status_text": "",
                            **_stats(text),
                        })
                report_payload["diffs"] = diffs
                report_html = render_report_html(report_payload)
                archive(..., report_html=report_html)
```

（注意：`_report_payload` 是否存在——Task 14 若没有提取这个函数，则 worker 里改用 `build_telemetry_bundle(run_events(run_id))` + 手动组装最小 payload（run 信息 + scorecard + telemetry + graph + budget/turn 摘要）。**先读 worker.py 与 reports.py 现状**，选择最小改动路径：优先复用，否则 worker 内组装。）

3c. 若 `_report_payload` 不存在：在 `reports.py` 提取公共函数 `build_report_payload(run_id, session, include)`（export_report 端点调用它），worker 用 `SessionLocal()` 调用。

- [ ] **Step 4: 运行测试**

Run: `cd apps/api && uv run pytest tests/test_run_archival.py tests/test_worker.py tests/test_reports.py tests/test_report_html.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add apps/api/app/scenario/sdk.py apps/api/app/worker.py apps/api/app/api/reports.py apps/api/tests/test_run_archival.py
git commit -m "feat: embed offline HTML report in run archive"
```

### Task 3: export 端点 `format=html`

**Files:**
- Modify: `apps/api/app/api/runs.py`（`export_run_archive`）
- Test: `apps/api/tests/test_run_artifacts.py`

- [ ] **Step 1: 写失败测试**

在 `apps/api/tests/test_run_artifacts.py` 追加：

```python
def test_export_html_from_archive(<fixture>) -> None:
    # 构造含 report.html 的 tar.gz 归档（成员 report.html = "<!doctype html>..."）
    response = client.get(f"/api/v1/runs/{run_id}/export?format=html")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert b"<!doctype html>" in response.content


def test_export_html_fallback_dynamic_render(<fixture>) -> None:
    # 无归档（或归档无 report.html）→ 动态渲染兜底，仍 200 text/html
    response = client.get(f"/api/v1/runs/{run_id}/export?format=html")
    assert response.status_code == 200
    assert b"<!doctype html>" in response.content
```

- [ ] **Step 2: 运行确认 FAIL**

- [ ] **Step 3: 实现**

`runs.py` `export_run_archive` 加分支（`format == "json"` 之后、tar.gz 之前）：

```python
    if format == "html":
        archive_path = Path(get_settings().artifact_root) / f"{run_id}.tar.gz"
        if archive_path.exists():
            import tarfile as tarfile_module

            with tarfile_module.open(archive_path, "r:gz") as source:
                member = next(
                    (m for m in source.getmembers() if m.isfile() and m.name == "report.html"),
                    None,
                )
                if member is not None:
                    content = source.extractfile(member).read()
                    return Response(
                        content,
                        media_type="text/html; charset=utf-8",
                        headers={"Content-Disposition": f'inline; filename="run-{run_id}.html"'},
                    )
        from app.api.reports import build_report_payload
        from app.report_html import render_report_html

        payload = build_report_payload(run_id, session, include="compact")
        html = render_report_html(payload)
        return Response(
            html.encode("utf-8"),
            media_type="text/html; charset=utf-8",
            headers={"Content-Disposition": f'inline; filename="run-{run_id}.html"'},
        )
```

- [ ] **Step 4: 运行测试**

Run: `cd apps/api && uv run pytest tests/test_run_artifacts.py tests/test_reports.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add apps/api/app/api/runs.py apps/api/tests/test_run_artifacts.py
git commit -m "feat: export run report as offline html"
```

### Task 4: 前端导出中心加 HTML 格式

**Files:**
- Modify: `apps/web/src/lib/api.ts`
- Modify: `apps/web/src/App.tsx`
- Test: `apps/web/src/lib/budget.test.ts`（不需要）→ 无新测试，跑现有

- [ ] **Step 1: api.ts**

`exportUrl` 的 format 类型加 `"html"`：

```ts
  exportUrl: (runId: string, format: "json" | "tar.gz" | "html", include: string[]) => {
    const params = new URLSearchParams({ format });
    if (format === "tar.gz" && include.length > 0 && !include.includes("all")) {
      params.set("include", include.join(","));
    }
    if (format === "json") {
      params.set("include", "compact");
    }
    return `${API_BASE}/runs/${runId}/export?${params.toString()}`;
  },
```

- [ ] **Step 2: App.tsx 导出中心**

- `useState<"json" | "tar.gz" | "html">` 加 "html" 选项
- radio 加第三项（HTML 图标用 FileCode2 或 FileText，lucide 现有 import 检查）；label 双语 "HTML 报告 / HTML report"，detail "自包含离线报告，打开即可查看 / Self-contained offline report"
- HTML 格式时：不显示内容多选（同 json）、不显示精简提示（HTML 是全量）；显示"包含完整页面内容（分数、图谱、审计、Diff、遥测），零外部依赖"提示
- 下载文件名：`run-{id}.html`（api.exportUrl 的 download 属性按 format 映射，html → `.html`）

- [ ] **Step 3: 运行 `cd apps/web && pnpm lint && pnpm test && pnpm build` 全部通过**

- [ ] **Step 4: 提交**

```bash
git add apps/web/src/lib/api.ts apps/web/src/App.tsx
git commit -m "feat: html report format in export center"
```

### Task 5: 收尾

**Files:**
- Modify: `CHANGELOG.md`（v0.14.0 条目补 HTML 报告）
- Modify: `docs/architecture.md`（归档契约补 report.html）

- [ ] **Step 1: CHANGELOG v0.14.0 条目追加**：离线 HTML 报告（归档内含 report.html、导出中心第 3 格式）
- [ ] **Step 2: docs/architecture.md 归档契约**：目录结构补 `report.html`（自包含离线报告）
- [ ] **Step 3: 全量回归**

```bash
cd apps/api && uv run ruff check . ../../scenarios && uv run pytest
cd apps/web && pnpm lint && pnpm test
./scripts/check-version.sh
```

Expected: 全部通过

- [ ] **Step 4: 提交**

```bash
git add CHANGELOG.md docs/architecture.md
git commit -m "docs: html report in changelog and archive contract"
```

---

## Self-Review 备注

1. `_report_payload`/`build_report_payload`：Task 2 3b/3c 需要先读 reports.py 现状决定复用或提取——若提取，`export_report` 与 worker 都调用它，注意 `include` 参数语义（worker 用 full-events 保证 HTML 事件完整）。
2. `render_report_html` 的 payload 契约与 reports v3 一致（run/scorecard/telemetry/budget_adjustments/turn_summary/diffs/graph）。
3. HTML 转义是安全关键点：所有动态内容必须过 `_esc()`；测试已覆盖 `<script>` 注入。
4. 事件流内嵌用 `json.dumps` 进 `<pre>`——内容本身含 `</pre>` 或 `<` 会被转义吗？`json.dumps` 不转义 `<`，但外层有 `_esc()`（payload 在 pre 里再 esc 一次即可）——实现时确认 pre 内容全部 `_esc` 包裹。
5. 不要 ruff format（格式噪音问题）；编辑用锚点脚本方式。
