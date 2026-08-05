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
        "budget_adjustments": {
            "count": 1,
            "first_at": "2026-08-05T00:10:00Z",
            "last_at": "2026-08-05T00:10:00Z",
            "fields": ["hard_tool_calls"],
        },
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
        "scorecard",
        "overview",
        "graph",
        "audit",
        "diffs",
        "telemetry",
        "overtime_penalty",
        "hard_tool_calls",
        "dead-letter",
        "README.md",
    ):
        assert marker in html


def test_html_diff_lines_are_classified() -> None:
    html = render_report_html(_payload())
    assert 'class="dl dl-add"' in html
    assert 'class="dl dl-del"' in html


def test_html_escapes_content() -> None:
    payload = _payload()
    payload["scorecard"] = {
        "score": 900,
        "maximum": 1200,
        "dimensions": [],
        "outcome": {"status": "evaluated", "censored": False},
    }
    payload["diffs"] = [
        {
            "repo": "<script>",
            "diff_text": "<script>alert(1)</script>",
            "status_text": "",
            "added_lines": 0,
            "removed_lines": 0,
            "file_count": 0,
        }
    ]
    html = render_report_html(payload)
    assert "<script>alert(1)</script>" not in html
