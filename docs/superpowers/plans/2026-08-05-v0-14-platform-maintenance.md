# v0.14.0 Platform Maintenance 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付预算动态调整、Diff 页面、Harness 优化、归档与导出优化四个功能（v0.14.0）。

**Architecture:** 预算热更新复用 pause 机制的 DB config 轮询（engine 每轮读 `config.budget_overrides` 应用到运行时预算，评分以场景仓库默认预算为准做超额线性扣分并标记 censored）；Diff 数据已存在于归档 tar.gz（`artifacts/*.diff` + `*.status`），新增 API 解析后前端加 tab 展示；Harness 优化围绕 engine 主循环（并行只读工具、状态分类退避重试、turn 事件、压缩触发升级、结果去重截断）；归档升级 schema v3（补预算调整/turn/资源账本/export.json），报告 JSON 改精简导出，新增导出中心 API 与 UI。

**Tech Stack:** Python 3.13 / FastAPI / SQLAlchemy / Pydantic v2 / pytest（后端）；React 18 / Vite / TypeScript / vitest（前端）；Rootless Docker 沙箱。

**Spec:** `docs/superpowers/specs/2026-08-05-budget-harness-diff-archive-design.md`

---

## Phase 1: 预算动态调整

### Task 1: Settings 增加扣分参数

**Files:**
- Modify: `apps/api/app/config.py:26-72`

- [ ] **Step 1: 写失败测试**

创建 `apps/api/tests/test_overtime.py`：

```python
from app.config import Settings


def test_overtime_settings_defaults() -> None:
    settings = Settings()
    assert settings.overtime_penalty_cap == 2.0
    assert settings.overtime_penalty_weights["active_time"] == 30
    assert settings.overtime_penalty_weights["tool_calls"] == 30
    assert settings.overtime_penalty_weights["provider_requests"] == 15
    assert settings.overtime_penalty_weights["total_tokens"] == 15
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_overtime.py -v`
Expected: FAIL（Settings 无这些字段）

- [ ] **Step 3: 实现**

在 `apps/api/app/config.py` 的 `Settings` 类中（`runner_context_emergency_characters` 附近）加：

```python
    overtime_penalty_cap: float = Field(default=2.0, ge=0.0)
    overtime_penalty_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "active_time": 30,
            "tool_calls": 30,
            "provider_requests": 15,
            "total_tokens": 15,
        }
    )
    provider_retry_jitter: float = Field(default=0.25, ge=0.0, le=0.5)
    provider_turn_timeout_seconds: int = Field(default=300, ge=0)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_overtime.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add apps/api/app/config.py apps/api/tests/test_overtime.py
git commit -m "feat: add overtime penalty and retry settings"
```

### Task 2: Engine 预算热更新

**Files:**
- Modify: `apps/api/app/runner/engine.py`（`__init__` 58-128、`run` 130-471、`_soft_budget_warning` 1471、`_finalization_nudge` 1548、`_on_provider_request` 1659、`_hard_resource_reasons` 1739、`_emit_hard_budget_event` 1751、`_resource_ledger` 1769）
- Modify: `apps/api/app/worker.py:389-400`（传 default_budget）

- [ ] **Step 1: 写失败测试**

在 `apps/api/tests/test_engine.py` 末尾追加：

```python
class BudgetOverrideClient:
    profile = SimpleNamespace(native_tools=True)

    def __init__(self) -> None:
        self.turns = 0

    def complete(self, messages: list[dict], tools: list[dict]) -> AssistantTurn:
        self.turns += 1
        if self.turns == 1:
            return AssistantTurn(
                tool_calls=[
                    ToolCall(call_id="t1", name="read_file", arguments={"path": "README.md"}),
                ],
                input_tokens=10,
                output_tokens=2,
            )
        return AssistantTurn(content="done", input_tokens=10, output_tokens=2)


class BudgetOverrideDB:
    """FakeSession 提供带 budget_overrides 的 run.config"""

    def __init__(self, config: dict) -> None:
        self._config = dict(config)

    def __enter__(self) -> "BudgetOverrideDB":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def get(self, model: type, run_id: object) -> object:
        return SimpleNamespace(config=self._config, tool_calls=0, input_tokens=0, output_tokens=0)


def test_budget_overrides_applied_at_runtime(tmp_path: Path, monkeypatch) -> None:
    scenario = load_scenario(SCENARIO_ROOT)
    prepared = PreparedScenario(
        scenario_root=SCENARIO_ROOT,
        workspace=tmp_path,
        metadata=scenario.metadata,
    )
    config = {
        "budget_overrides": [
            {
                "field": "hard_tool_calls",
                "value": 5000,
                "reason": "keep going",
                "requested_by": "test",
                "requested_at": "2026-08-05T00:00:00Z",
            }
        ]
    }
    monkeypatch.setattr(engine_module, "SessionLocal", lambda: BudgetOverrideDB(config))
    engine = AgentEngine(
        run_id=uuid.uuid4(),
        client=BudgetOverrideClient(),
        sandbox=SimpleNamespace(),
        prepared=prepared,
        faults=FaultController([]),
    )
    monkeypatch.setattr(
        engine,
        "_event",
        lambda kind, payload: engine.events.append({"kind": kind, **payload}),
    )
    monkeypatch.setattr(engine, "_execute", lambda call: ToolResult(call_id=call.call_id, name=call.name, status="ok", output="x"))
    monkeypatch.setattr(engine, "_completion_gaps", lambda: [])
    monkeypatch.setattr(engine, "_compact_context", lambda *a, **k: None)
    result = engine.run(prepared)
    assert engine.budget.hard_tool_calls == 5000
    assert result.private_state["hard_budget_reasons"] == []
    assert any(e["kind"] == "run.budget_adjusted" for e in engine.events)
    adjusted = [e for e in engine.events if e["kind"] == "run.budget_adjusted"][0]
    assert adjusted["field"] == "hard_tool_calls"
    assert adjusted["new_value"] == 5000
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_engine.py::test_budget_overrides_applied_at_runtime -v`
Expected: FAIL（AttributeError: no attribute budget / 无 budget_adjusted 事件）

- [ ] **Step 3: 实现 engine**

3a. `AgentEngine.__init__` 增加参数与字段（`engine.py:58-70` 签名加 `default_budget: BudgetSpec | None = None`，`engine.py:80-128` 区域加）：

```python
        from app.challenge.spec import BudgetSpec  # 顶部 import 区已含则省略
        self.budget = self.prepared.metadata.budget
        self.default_budget = default_budget or self.prepared.metadata.budget
        self.applied_budget_overrides = 0
```

3b. `run()` 中 `engine.py:163-164` 删除 `hard_calls`/`hard_seconds` 局部变量，循环条件改为：

```python
        while (
            self.tool_calls < self.budget.hard_tool_calls
            and self._active_elapsed() < self.budget.hard_seconds
        ):
            if not self._wait_for_resume():
                final_response = "Run cancelled."
                break
            self._apply_budget_overrides()
```

3c. `engine.py:342` 循环内 `if self.tool_calls >= hard_calls:` 改为 `if self.tool_calls >= self.budget.hard_tool_calls:`；`engine.py:426-431` 的 `reached` 计算改为引用 `self.budget`。

3d. 全部 `self.prepared.metadata.budget` 替换为 `self.budget`（行 1472、1554、1661、1740、1752 等，用 `rg -n "prepared.metadata.budget" apps/api/app/runner/engine.py` 确认无遗漏）。

3e. 新增方法（放在 `_on_provider_request` 之后）：

```python
    def _apply_budget_overrides(self) -> None:
        with SessionLocal() as session:
            run = session.get(BenchmarkRun, self.run_id)
            overrides = list(dict(run.config).get("budget_overrides", [])) if run else []
        for entry in overrides[self.applied_budget_overrides :]:
            field = str(entry.get("field", ""))
            if not hasattr(self.budget, field):
                continue
            old_value = getattr(self.budget, field)
            new_value = entry.get("value")
            try:
                self.budget = self.budget.model_copy(update={field: int(new_value) if new_value is not None else None})
            except (TypeError, ValueError):
                continue
            self.applied_budget_overrides += 1
            self._event(
                "run.budget_adjusted",
                {
                    "field": field,
                    "old_value": old_value,
                    "new_value": getattr(self.budget, field),
                    "reason": str(entry.get("reason", "")),
                    "requested_by": str(entry.get("requested_by", "")),
                    "requested_at": str(entry.get("requested_at", "")),
                },
            )
```

3f. `_resource_ledger`（1769 起）在返回 dict 的 `budgets` 旁加：

```python
            "default_budget": self.default_budget.model_dump(mode="json"),
```

3g. `worker.py:389-400` 创建 engine 时传 `default_budget=scenario.metadata.budget`：

```python
                engine = AgentEngine(
                    run_id=run_id,
                    client=candidate_client,
                    sandbox=sandbox,
                    prepared=prepared,
                    faults=faults,
                    default_budget=scenario.metadata.budget,
                    ...
                )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_engine.py -v`
Expected: 全部 PASS（含新测试与既有预算测试）

- [ ] **Step 5: 提交**

```bash
git add apps/api/app/runner/engine.py apps/api/app/worker.py apps/api/tests/test_engine.py
git commit -m "feat: hot-apply runtime budget overrides in engine"
```

### Task 3: 超额扣分与 censored 判定（overtime 模块 + worker 集成）

**Files:**
- Create: `apps/api/app/overtime.py`
- Modify: `apps/api/app/worker.py:463-464`
- Test: `apps/api/tests/test_overtime.py`

- [ ] **Step 1: 写失败测试**

在 `apps/api/tests/test_overtime.py` 追加：

```python
from types import SimpleNamespace

import pytest

from app.challenge.spec import BudgetSpec
from app.overtime import apply_overtime_penalty, final_usage


def _result(**overrides: object) -> object:
    private_state = {
        "provider_requests": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        **overrides,
    }
    return SimpleNamespace(
        elapsed_seconds=10,
        tool_calls=10,
        private_state=private_state,
    )


def test_no_overrun_no_penalty() -> None:
    default = BudgetSpec(soft_seconds=100, hard_seconds=200, soft_tool_calls=50, hard_tool_calls=100)
    scorecard = {"score": 900, "maximum": 1200, "outcome": {"status": "evaluated", "censored": False}}
    apply_overtime_penalty(scorecard, _result(), default)
    assert scorecard["score"] == 900
    assert scorecard["overtime_penalty"]["total_penalty"] == 0


def test_overrun_triggers_censored_and_linear_penalty() -> None:
    default = BudgetSpec(soft_seconds=100, hard_seconds=200, soft_tool_calls=50, hard_tool_calls=100)
    result = _result(provider_requests=10, input_tokens=50, output_tokens=50)
    result.elapsed_seconds = 300   # overrun = (300-200)/200 = 0.5
    result.tool_calls = 250        # overrun = (250-100)/100 = 1.5
    scorecard = {"score": 900, "maximum": 1200, "outcome": {"status": "evaluated", "censored": False}}
    apply_overtime_penalty(scorecard, result, default)
    assert scorecard["outcome"]["censored"] is True
    assert "exceeded_default_budget" in scorecard["outcome"]["hard_budget_reasons"]
    expected = round(0.5 * 30 + 1.5 * 30, 2)   # active_time + tool_calls weights
    assert scorecard["score"] == max(0.0, 900 - expected)
    assert scorecard["overtime_penalty"]["total_penalty"] == expected


def test_penalty_floor_zero_and_cap() -> None:
    default = BudgetSpec(soft_seconds=100, hard_seconds=200, soft_tool_calls=50, hard_tool_calls=100)
    result = _result()
    result.elapsed_seconds = 2000  # overrun capped at 2.0
    result.tool_calls = 10000      # overrun capped at 2.0
    scorecard = {"score": 10, "maximum": 1200, "outcome": {"status": "evaluated", "censored": False}}
    apply_overtime_penalty(scorecard, result, default)
    assert scorecard["score"] == 0.0
    assert scorecard["overtime_penalty"]["active_time"]["overrun"] == 2.0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_overtime.py -v`
Expected: FAIL（ImportError: cannot import name）

- [ ] **Step 3: 实现**

创建 `apps/api/app/overtime.py`：

```python
from __future__ import annotations

from typing import Any

from app.challenge.spec import BudgetSpec


def final_usage(result: Any) -> dict[str, int]:
    private_state = result.private_state or {}
    return {
        "active_time": int(result.elapsed_seconds or 0),
        "tool_calls": int(result.tool_calls or 0),
        "provider_requests": int(private_state.get("provider_requests", 0)),
        "total_tokens": int(private_state.get("input_tokens", 0)) + int(
            private_state.get("output_tokens", 0)
        ),
    }


def apply_overtime_penalty(
    scorecard: dict[str, Any],
    result: Any,
    default_budget: BudgetSpec,
    *,
    cap: float = 2.0,
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    weights = weights or {
        "active_time": 30,
        "tool_calls": 30,
        "provider_requests": 15,
        "total_tokens": 15,
    }
    usage = final_usage(result)
    hard = {
        "active_time": default_budget.hard_seconds,
        "tool_calls": default_budget.hard_tool_calls,
        "provider_requests": default_budget.hard_provider_requests,
        "total_tokens": default_budget.hard_total_tokens,
    }
    per_dimension: dict[str, Any] = {}
    exceeded: list[str] = []
    total_penalty = 0.0
    for name, hard_value in hard.items():
        used = usage[name]
        if hard_value is None:
            per_dimension[name] = {"used": used, "hard": None, "overrun": 0.0, "penalty": 0.0}
            continue
        overrun = max(0.0, (used - hard_value) / hard_value) if hard_value else 0.0
        overrun = min(overrun, cap)
        penalty = round(overrun * weights.get(name, 0.0), 2)
        total_penalty += penalty
        if overrun > 0:
            exceeded.append(name)
        per_dimension[name] = {"used": used, "hard": hard_value, "overrun": round(overrun, 4), "penalty": penalty}

    score = float(scorecard.get("score", 0.0))
    score_after = max(0.0, score - total_penalty)
    outcome = dict(scorecard.get("outcome") or {})
    if exceeded:
        outcome["status"] = "budget_exhausted"
        outcome["censored"] = True
        reasons = list(outcome.get("hard_budget_reasons") or [])
        if "exceeded_default_budget" not in reasons:
            reasons.append("exceeded_default_budget")
        outcome["hard_budget_reasons"] = reasons
        scorecard["outcome"] = outcome
    scorecard["score"] = round(score_after, 2)
    scorecard["overtime_penalty"] = {
        "cap": cap,
        "weights": dict(weights),
        "usage": usage,
        "dimensions": per_dimension,
        "total_penalty": round(total_penalty, 2),
        "score_before": round(score, 2),
        "score_after": round(score_after, 2),
    }
    return scorecard
```

- [ ] **Step 4: worker 集成**

`apps/api/app/worker.py:463-464` 的 `scorecard = scenario.grade(prepared, result)` 之后插入：

```python
                from app.overtime import apply_overtime_penalty

                apply_overtime_penalty(
                    scorecard,
                    result,
                    scenario.metadata.budget,
                    cap=settings.overtime_penalty_cap,
                    weights=settings.overtime_penalty_weights,
                )
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_overtime.py tests/test_worker.py::test_budget_exhausted_run_is_archived_as_censored_outcome -v`
Expected: 全部 PASS

- [ ] **Step 6: 提交**

```bash
git add apps/api/app/overtime.py apps/api/app/worker.py apps/api/tests/test_overtime.py
git commit -m "feat: overtime penalty and censored via default budget"
```

### Task 4: API `POST /runs/{id}/budget`

**Files:**
- Modify: `apps/api/app/schemas.py:290-334`
- Modify: `apps/api/app/api/runs.py`（末尾，`active_run_count` 之前）
- Test: `apps/api/tests/test_run_control.py`

- [ ] **Step 1: 写失败测试**

在 `apps/api/tests/test_run_control.py` 末尾追加（先读该文件现有 fixture 风格，沿用其 app/client 构造）：

```python
def test_adjust_budget_rejects_finished_run(client, app) -> None:
    run = <按 test_run_control.py 现有方式创建 completed run>
    response = client.post(
        f"/api/v1/runs/{run.id}/budget",
        json={"hard_tool_calls": 5000, "reason": "keep going"},
    )
    assert response.status_code == 409


def test_adjust_budget_appends_override(client, app) -> None:
    run = <按现有方式创建 running run>
    response = client.post(
        f"/api/v1/runs/{run.id}/budget",
        json={"hard_tool_calls": 5000, "reason": "keep going"},
    )
    assert response.status_code == 200
    payload = response.json()
    overrides = payload["config"]["budget_overrides"]
    assert overrides[-1]["field"] == "hard_tool_calls"
    assert overrides[-1]["value"] == 5000


def test_adjust_budget_rejects_token_for_antigravity(client, app) -> None:
    run = <antigravity provider 的 running run>
    response = client.post(
        f"/api/v1/runs/{run.id}/budget",
        json={"hard_total_tokens": 1_000_000, "reason": "tokens"},
    )
    assert response.status_code == 400
```

（按 test_run_control.py 的实际 fixture 风格补齐 run 创建代码——先阅读该文件再写。）

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_run_control.py -v`
Expected: FAIL（404 route / 无 budget_overrides）

- [ ] **Step 3: 实现 schema**

`apps/api/app/schemas.py` 在 `RunCreate` 之后加：

```python
class BudgetAdjustment(BaseModel):
    soft_seconds: int | None = Field(default=None, ge=60, le=43_200)
    hard_seconds: int | None = Field(default=None, ge=300, le=86_400)
    soft_tool_calls: int | None = Field(default=None, ge=10, le=10_000)
    hard_tool_calls: int | None = Field(default=None, ge=20, le=20_000)
    soft_provider_requests: int | None = Field(default=None, ge=1, le=10_000)
    hard_provider_requests: int | None = Field(default=None, ge=2, le=20_000)
    soft_total_tokens: int | None = Field(default=None, ge=1_000, le=4_000_000_000)
    hard_total_tokens: int | None = Field(default=None, ge=2_000, le=8_000_000_000)
    reason: str = Field(min_length=1, max_length=200)
```

- [ ] **Step 4: 实现端点**

`apps/api/app/api/runs.py` 在 `cancel_run` 之前加：

```python
@router.post("/{run_id}/budget", response_model=RunRead)
def adjust_run_budget(
    run_id: uuid.UUID,
    payload: BudgetAdjustment,
    session: Session = Depends(get_session),
    user: UserAccount = Depends(csrf_protection),
) -> BenchmarkRun:
    run = session.get(BenchmarkRun, run_id)
    if not can_access_run(session, user, run):
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status not in {RunStatus.queued, RunStatus.preparing, RunStatus.running}:
        raise HTTPException(
            status_code=409,
            detail="Budget can only be adjusted while the run is active",
        )
    candidate_snapshot = dict(run.config).get("candidate_model_snapshot", {})
    if (
        candidate_snapshot.get("provider") == "antigravity"
        and (
            payload.soft_total_tokens is not None
            or payload.hard_total_tokens is not None
        )
    ):
        raise HTTPException(
            status_code=400,
            detail="Antigravity CLI does not expose machine-readable token usage",
        )
    task = session.get(TaskDefinition, run.task_id)
    scenario_budget = dict(task.manifest.get("budget", {})) if task else {}
    current = dict(scenario_budget)
    current.update(dict(run.config))
    for override in list(dict(run.config).get("budget_overrides", [])):
        current[override["field"]] = override["value"]
    merged = {
        field: getattr(payload, field) if getattr(payload, field) is not None else current.get(field)
        for field in (
            "soft_seconds",
            "hard_seconds",
            "soft_tool_calls",
            "hard_tool_calls",
            "soft_provider_requests",
            "hard_provider_requests",
            "soft_total_tokens",
            "hard_total_tokens",
        )
    }
    try:
        BudgetSpec(**merged)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    config = dict(run.config)
    config.setdefault("budget_overrides", [])
    config["budget_overrides"] = list(config["budget_overrides"]) + [
        {
            "field": field,
            "value": getattr(payload, field),
            "reason": payload.reason,
            "requested_by": user.username if hasattr(user, "username") else str(user.id),
            "requested_at": datetime.now(UTC).isoformat(),
        }
        for field in (
            "soft_seconds",
            "hard_seconds",
            "soft_tool_calls",
            "hard_tool_calls",
            "soft_provider_requests",
            "hard_provider_requests",
            "soft_total_tokens",
            "hard_total_tokens",
        )
        if getattr(payload, field) is not None
    ]
    run.config = config
    append_event(
        session,
        run.id,
        "run.budget_adjustment_requested",
        {"reason": payload.reason, "fields": [e["field"] for e in config["budget_overrides"][-1:]]},
    )
    session.commit()
    session.refresh(run)
    return run
```

（顶部 import 补：`from app.challenge.spec import BudgetSpec`、`from app.schemas import BudgetAdjustment, ...`、`from datetime import UTC, datetime`。）

- [ ] **Step 5: 运行测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_run_control.py -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add apps/api/app/schemas.py apps/api/app/api/runs.py apps/api/tests/test_run_control.py
git commit -m "feat: POST /runs/{id}/budget dynamic adjustment endpoint"
```

### Task 5: 前端预算调整 UI

**Files:**
- Modify: `apps/web/src/lib/api.ts:103-131`
- Modify: `apps/web/src/lib/types.ts:352-405`
- Modify: `apps/web/src/App.tsx`（RunDetailPage 2005-2102、底部按钮区 2475-2540）

- [ ] **Step 1: 类型与 API**

`apps/web/src/lib/types.ts` 加：

```ts
export interface BudgetOverrideEntry {
  field: string;
  value: number | null;
  reason: string;
  requested_by: string;
  requested_at: string;
}

export interface BudgetAdjustment {
  soft_seconds?: number;
  hard_seconds?: number;
  soft_tool_calls?: number;
  hard_tool_calls?: number;
  soft_provider_requests?: number | null;
  hard_provider_requests?: number | null;
  soft_total_tokens?: number | null;
  hard_total_tokens?: number | null;
  reason: string;
}
```

`apps/web/src/lib/api.ts` 的 `api` 对象加：

```ts
  adjustBudget: (runId: string, payload: BudgetAdjustment) =>
    request(`/runs/${runId}/budget`, { method: "POST", body: JSON.stringify(payload) }),
```

（import BudgetAdjustment 到 api.ts。）

- [ ] **Step 2: 写失败测试（前端）**

创建 `apps/web/src/lib/budget.test.ts`：

```ts
import { describe, expect, it } from "vitest";
import { mergeBudgetOverrides } from "./budget";

describe("mergeBudgetOverrides", () => {
  it("applies overrides onto base budget", () => {
    const base = { hard_tool_calls: 2200, hard_seconds: 21600 };
    const overrides = [
      { field: "hard_tool_calls", value: 5000, reason: "r", requested_by: "u", requested_at: "t" },
    ];
    expect(mergeBudgetOverrides(base, overrides)).toEqual({ hard_tool_calls: 5000, hard_seconds: 21600 });
  });
});
```

创建 `apps/web/src/lib/budget.ts`：

```ts
import type { BudgetOverrideEntry } from "./types";

export function mergeBudgetOverrides(
  base: Record<string, number | null>,
  overrides: BudgetOverrideEntry[],
): Record<string, number | null> {
  const merged = { ...base };
  for (const entry of overrides) {
    if (entry.field in merged && entry.value !== null) {
      merged[entry.field] = entry.value;
    }
  }
  return merged;
}
```

- [ ] **Step 3: 运行测试确认失败→通过**

Run: `cd apps/web && pnpm test -- budget`
Expected: 先 FAIL（无 budget.ts），实现后 PASS

- [ ] **Step 4: RunDetailPage 加调整按钮与弹窗**

在 `apps/web/src/App.tsx` RunDetailPage 的暂停/恢复按钮区（约 2475-2490）旁加"调整预算"按钮（`running && !pauseRequested` 时显示），点击打开弹窗：8 个数字输入（从当前运行时预算预填：`data.config.budget_overrides` 合并后的值，若无则 task manifest budget）+ reason 必填文本 + 提交调 `adjustBudget` 后 `queryClient.invalidateQueries`。弹窗用现有 modal 风格（参照 App.tsx 内已有 modal 组件模式）。

调整历史展示：RunDetailPage 事件列表中 `run.budget_adjusted` 事件已会出现在 audit tab；另在弹窗内展示 `budget_overrides` 全部条目（含 reason/时间）。

- [ ] **Step 5: 提交**

```bash
git add apps/web/src/lib/api.ts apps/web/src/lib/types.ts apps/web/src/lib/budget.ts apps/web/src/lib/budget.test.ts apps/web/src/App.tsx
git commit -m "feat: adjust budget UI in run detail page"
```

**Phase 1 验收点**：`cd apps/api && uv run pytest tests/test_engine.py tests/test_overtime.py tests/test_run_control.py -q` 全绿；`cd apps/web && pnpm test && pnpm lint` 通过。

---

## Phase 2: Diff 页面

### Task 6: API `GET /runs/{id}/diffs`

**Files:**
- Create: `apps/api/app/api/diffs.py`
- Modify: `apps/api/app/main.py:59-62`
- Test: `apps/api/tests/test_reports.py`

- [ ] **Step 1: 写失败测试**

在 `apps/api/tests/test_reports.py` 末尾追加（先读该文件现有 fixture 与归档构造方式）：

```python
def test_run_diffs_parsed_from_archive(client, app, tmp_path, monkeypatch) -> None:
    # 按 test_reports.py 现有方式创建 run，并手工在 settings.artifact_root 写一个
    # {run_id}.tar.gz，内含 artifacts/dead-letter.diff 与 artifacts/dead-letter.status
    # diff 内容示例:
    #   diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n@@ -1,1 +1,2 @@\n- old\n+ new\n
    response = client.get(f"/api/v1/runs/{run.id}/diffs")
    assert response.status_code == 200
    body = response.json()
    assert body[0]["repo"] == "dead-letter"
    assert body[0]["added_lines"] == 1
    assert body[0]["removed_lines"] == 1
    assert body[0]["file_count"] == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_reports.py -v`
Expected: FAIL（404 route）

- [ ] **Step 3: 实现**

创建 `apps/api/app/api/diffs.py`：

```python
import re
import tarfile
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_session
from app.models import BenchmarkRun, UserAccount
from app.security import can_access_run, current_user

router = APIRouter(prefix="/runs", tags=["diffs"])

_DIFF_FILE = re.compile(r"^diff --git ")


def _archive_candidates(run_id: uuid.UUID) -> list[Path]:
    root = Path(get_settings().artifact_root)
    return [
        root / f"{run_id}.tar.gz",
        root / f"{run_id}-failure-checkpoint.tar.gz",
    ]


def _stats(diff_text: str) -> dict[str, int]:
    added = removed = 0
    files = 0
    for line in diff_text.splitlines():
        if _DIFF_FILE.match(line):
            files += 1
        elif line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return {"added_lines": added, "removed_lines": removed, "file_count": files}


def _read_members(tar_path: Path) -> list[dict[str, str]]:
    repos: dict[str, dict[str, str]] = {}
    with tarfile.open(tar_path, "r:gz") as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            path = member.name
            if not path.startswith("artifacts/") or not (
                path.endswith(".diff") or path.endswith(".status")
            ):
                continue
            repo = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
            entry = repos.setdefault(repo, {})
            entry["status_text" if path.endswith(".status") else "diff_text"] = (
                archive.extractfile(member).read().decode("utf-8", errors="replace")
            )
    return [
        {"repo": repo, "diff_text": data.get("diff_text", ""), "status_text": data.get("status_text", "")}
        for repo, data in sorted(repos.items())
    ]


@router.get("/{run_id}/diffs")
def run_diffs(
    run_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: UserAccount = Depends(current_user),
) -> list[dict[str, object]]:
    run = session.get(BenchmarkRun, run_id)
    if not can_access_run(session, user, run):
        raise HTTPException(status_code=404, detail="Run not found")
    for candidate in _archive_candidates(run_id):
        if candidate.exists():
            diffs = []
            for entry in _read_members(candidate):
                stats = _stats(entry["diff_text"])
                diffs.append({**entry, **stats})
            return diffs
    raise HTTPException(status_code=404, detail="No run archive available")
```

`apps/api/app/main.py:59-62` 的 api_router 列表加入 `diffs.router`。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_reports.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add apps/api/app/api/diffs.py apps/api/app/main.py apps/api/tests/test_reports.py
git commit -m "feat: GET /runs/{id}/diffs endpoint"
```

### Task 7: 前端 Diff tab 与 DiffViewer

**Files:**
- Modify: `apps/web/src/lib/api.ts`
- Modify: `apps/web/src/lib/types.ts`
- Create: `apps/web/src/components/DiffViewer.tsx`
- Modify: `apps/web/src/App.tsx`（tab union 2005、tab 按钮 2209-2241、内容区 2286-2287 附近）
- Modify: `apps/web/src/styles.css`
- Test: `apps/web/src/components/DiffViewer.test.ts`

- [ ] **Step 1: 类型与 API**

`types.ts`：

```ts
export interface RunDiff {
  repo: string;
  diff_text: string;
  status_text: string;
  added_lines: number;
  removed_lines: number;
  file_count: number;
}
```

`api.ts`：

```ts
  runDiffsUrl: (runId: string) => `${API_BASE}/runs/${runId}/diffs`,
```

- [ ] **Step 2: 写失败测试（DiffViewer 解析）**

`apps/web/src/components/DiffViewer.test.ts`：

```ts
import { describe, expect, it } from "vitest";
import { splitDiffFiles, DiffLineType, classifyLine } from "./DiffViewer";

const SAMPLE = [
  "diff --git a/README.md b/README.md",
  "--- a/README.md",
  "+++ b/README.md",
  "@@ -1,1 +1,2 @@",
  "- old",
  "+ new",
].join("\n");

describe("splitDiffFiles", () => {
  it("splits unified diff into per-file blocks", () => {
    const blocks = splitDiffFiles(SAMPLE);
    expect(blocks).toHaveLength(1);
    expect(blocks[0].path).toBe("README.md");
  });
});

describe("classifyLine", () => {
  it("classifies +/-/context lines", () => {
    expect(classifyLine("+ new")).toBe(DiffLineType.Added);
    expect(classifyLine("- old")).toBe(DiffLineType.Removed);
    expect(classifyLine("  ctx")).toBe(DiffLineType.Context);
    expect(classifyLine("@@ -1,1 +1,2 @@")).toBe(DiffLineType.Hunk);
  });
});
```

- [ ] **Step 3: 实现 DiffViewer**

`components/DiffViewer.tsx`（核心逻辑，UI 用现有 css 风格）：

```tsx
import { useMemo, useState } from "react";
import type { RunDiff } from "../lib/types";

export enum DiffLineType {
  Added = "added",
  Removed = "removed",
  Context = "context",
  Hunk = "hunk",
}

export interface DiffFileBlock {
  path: string;
  lines: { type: DiffLineType; text: string }[];
}

export function classifyLine(line: string): DiffLineType {
  if (line.startsWith("@@")) return DiffLineType.Hunk;
  if (line.startsWith("+") && !line.startsWith("+++")) return DiffLineType.Added;
  if (line.startsWith("-") && !line.startsWith("---")) return DiffLineType.Removed;
  return DiffLineType.Context;
}

export function splitDiffFiles(diffText: string): DiffFileBlock[] {
  const blocks: DiffFileBlock[] = [];
  let current: DiffFileBlock | null = null;
  for (const raw of diffText.split("\n")) {
    if (raw.startsWith("diff --git ")) {
      if (current) blocks.push(current);
      const match = /diff --git a\/(\S+) b\//.exec(raw);
      current = { path: match?.[1] ?? raw, lines: [] };
    }
    if (current) current.lines.push({ type: classifyLine(raw), text: raw });
  }
  if (current) blocks.push(current);
  return blocks;
}
```

组件主体：props `{ diffs: RunDiff[] }`；顶部 repo 选择（含 +X −Y 徽标与 status 摘要 `<pre>`）；正文按文件折叠（`<details>`），每文件渲染行号 + 着色行（`line-${type}` class）。UI 细节对齐 `styles.css` 现有卡片/圆角风格。

- [ ] **Step 4: App.tsx 集成**

- tab union（2005 行）加 `"diff"`；
- tab 按钮区（2235 后）加 `<button className={tab === "diff" ? "active" : ""} onClick={() => setTab("diff")}>diff</button>`；
- 内容区加：

```tsx
      {tab === "diff" && <DiffTab runId={runId} />}
```

- 定义 `DiffTab`：`useQuery({ queryKey: ["run-diffs", runId], queryFn: () => fetch(api.runDiffsUrl(runId)).then(r => r.json()) })`，loading/error/空态处理，成功渲染 `<DiffViewer diffs={data} />`。

- [ ] **Step 5: 运行测试与 lint**

Run: `cd apps/web && pnpm test -- DiffViewer && pnpm lint`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add apps/web/src/lib/api.ts apps/web/src/lib/types.ts apps/web/src/components/DiffViewer.tsx apps/web/src/components/DiffViewer.test.ts apps/web/src/App.tsx
git commit -m "feat: diff tab with DiffViewer in run detail page"
```

**Phase 2 验收点**：diff 端点测试通过；`pnpm lint` 通过。

---

## Phase 3: Harness 优化

### Task 8: 并行工具调用（只读工具）

**Files:**
- Modify: `apps/api/app/runner/engine.py`（工具循环 340-423、`__init__` 加锁、`_execute` 计数加锁）
- Test: `apps/api/tests/test_engine.py`

- [ ] **Step 1: 写失败测试**

在 `apps/api/tests/test_engine.py` 末尾追加：

```python
class ParallelToolClient:
    profile = SimpleNamespace(native_tools=True)

    def __init__(self) -> None:
        self.turn = 0

    def complete(self, messages: list[dict], tools: list[dict]) -> AssistantTurn:
        self.turn += 1
        if self.turn == 1:
            return AssistantTurn(
                tool_calls=[
                    ToolCall(call_id="p1", name="read_file", arguments={"path": "a.txt"}),
                    ToolCall(call_id="p2", name="list_files", arguments={"path": "."}),
                    ToolCall(call_id="p3", name="write_file", arguments={"path": "b.txt", "content": "x"}),
                    ToolCall(call_id="p4", name="read_file", arguments={"path": "a.txt"}),
                ],
                input_tokens=10,
                output_tokens=2,
            )
        return AssistantTurn(content="done", input_tokens=10, output_tokens=2)


def test_parallel_safe_tools_execute_and_keep_event_order(tmp_path: Path, monkeypatch) -> None:
    scenario = load_scenario(SCENARIO_ROOT)
    prepared = PreparedScenario(
        scenario_root=SCENARIO_ROOT,
        workspace=tmp_path,
        metadata=scenario.metadata,
    )
    executed: list[str] = []
    running = {"max_concurrent": 0, "now": 0}

    def fake_execute(call: ToolCall) -> ToolResult:
        running["now"] += 1
        running["max_concurrent"] = max(running["max_concurrent"], running["now"])
        executed.append(call.call_id)
        running["now"] -= 1
        return ToolResult(call_id=call.call_id, name=call.name, status="ok", output=f"out:{call.name}")

    monkeypatch.setattr(engine_module, "SessionLocal", lambda: SimpleNamespace())
    engine = AgentEngine(
        run_id=uuid.uuid4(),
        client=ParallelToolClient(),
        sandbox=SimpleNamespace(),
        prepared=prepared,
        faults=FaultController([]),
    )
    monkeypatch.setattr(engine, "_event", lambda kind, payload: engine.events.append({"kind": kind, **payload}))
    monkeypatch.setattr(engine, "_execute", fake_execute)
    monkeypatch.setattr(engine, "_completion_gaps", lambda: [])
    monkeypatch.setattr(engine, "_compact_context", lambda *a, **k: None)
    engine.run(prepared)
    assert executed == ["p1", "p2", "p3", "p4"]
    assert running["max_concurrent"] >= 2
    calls = [e for e in engine.events if e["kind"] == "tool.call"]
    assert [e["call_id"] for e in calls] == ["p1", "p2", "p3", "p4"]
```

（注意：`fake_execute` 用 `running["now"]` 模拟并发；write_file 是非 safe 工具必须串行且在 read/list 批次之后执行。）

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_engine.py::test_parallel_safe_tools_execute_and_keep_event_order -v`
Expected: FAIL（max_concurrent == 1）

- [ ] **Step 3: 实现**

3a. `engine.py` 顶部 import 加 `from concurrent.futures import ThreadPoolExecutor` 与 `import threading`；常量区加：

```python
PARALLEL_SAFE_TOOLS = frozenset(
    {"list_files", "read_file", "browser_search", "browser_open", "browser_find"}
)
PARALLEL_MAX_WORKERS = 4
```

3b. `__init__` 加：`self._ledger_lock = threading.Lock()`、`self._parallel_executor: ThreadPoolExecutor | None = None`。

3c. 重构 `run()` 工具循环（340-423 行）为"分批执行 + 顺序处理"：

```python
            stop_requested = False
            pending: list[ToolCall] = []
            results: dict[str, ToolResult] = {}

            def flush() -> None:
                nonlocal pending, results
                if not pending:
                    return
                if len(pending) > 1:
                    with ThreadPoolExecutor(max_workers=PARALLEL_MAX_WORKERS) as pool:
                        futures = {pool.submit(self._execute, call): call for call in pending}
                        for call in pending:
                            results[call.call_id] = futures[call.call_id].result() if False else next(
                                future.result() for future, c in ((f, c) for f, c in futures.items()) if c.call_id == call.call_id
                            )
                else:
                    results[pending[0].call_id] = self._execute(pending[0])
                pending = []

            for call in turn.tool_calls:
                if self.tool_calls >= self.budget.hard_tool_calls:
                    break
                if not self._wait_for_resume():
                    final_response = "Run cancelled."
                    stop_requested = True
                    break
                parallel_safe = call.name in PARALLEL_SAFE_TOOLS
                if not parallel_safe:
                    flush()
                self.tool_calls += 1
                signature = tool_call_signature(call)
                self.tool_signature_counts[signature] += 1
                self._event("tool.call", { ...原 payload，保持不动... })
                if parallel_safe:
                    pending.append(call)
                else:
                    results[call.call_id] = self._execute(call)
                self._process_tool_result(
                    call, results[call.call_id], turn_number,
                )
            flush()
            if stop_requested:
                break
```

（实现时把原 367-422 行的"执行+事件+状态机+快照"逻辑提取为 `_process_tool_result(self, call, result, turn_number)`，保证事件/incident/release advance 都在主线程按声明序执行；`tool.result` 事件输出保持原样。）

3d. `_execute` 内 `read_counts`/`write_counts` 的更新（1167-1172 行）用锁包住：

```python
                    if call.name == "read_file":
                        with self._ledger_lock:
                            self.read_counts[path] += 1
                    elif call.name == "write_file":
                        with self._ledger_lock:
                            result.metadata["blind_write"] = not self._path_was_observed(path)
                            self.write_counts[path] += 1
                            result.metadata["write_ordinal"] = self.write_counts[path]
```

3e. 因 ThreadPoolExecutor 每次新建的开销，改为 `self._parallel_executor` 复用（engine 生命周期内 lazy 创建，`checkpoint_result`/结束处不强制 shutdown——进程退出自然回收；如需要可在 `ScenarioRunResult` 返回前 `self._parallel_executor.shutdown(wait=True)` 保证事件完整性）。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_engine.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add apps/api/app/runner/engine.py apps/api/tests/test_engine.py
git commit -m "feat: parallel execution of read-only tools"
```

### Task 9: Provider 弹性退避重试

**Files:**
- Modify: `apps/api/app/runner/providers.py:1720-1740`（`provider_retry_delay`、`provider_transport_retry_delay`）
- Modify: `apps/api/app/worker.py:378-387`（candidate client 传 timeout）
- Test: `apps/api/tests/test_providers.py`

- [ ] **Step 1: 写失败测试**

在 `apps/api/tests/test_providers.py` 末尾追加：

```python
def test_retry_delay_is_status_class_based_and_jittered() -> None:
    from app.runner import providers as p

    response_429 = SimpleNamespace(headers={}, status_code=429)
    response_503 = SimpleNamespace(headers={}, status_code=503)
    delays_429 = [p.provider_retry_delay(response_429, 0) for _ in range(20)]
    delays_503 = [p.provider_retry_delay(response_503, 0) for _ in range(20)]
    # 429 基础退避更大且带抖动（±25%）
    assert all(d >= 3.0 for d in delays_429)
    assert all(0.75 <= d <= 1.25 for d in delays_503)
    assert len(set(round(d, 3) for d in delays_429)) > 1
    assert len(set(round(d, 3) for d in delays_503)) > 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_providers.py::test_retry_delay_is_status_class_based_and_jittered -v`
Expected: FAIL（现无抖动、无分类）

- [ ] **Step 3: 实现**

替换 `providers.py` 两个 delay 函数：

```python
import random


def _jittered(delay: float, ratio: float = 0.25) -> float:
    if ratio <= 0:
        return round(delay, 3)
    return round(max(0.25, delay * (1 + random.uniform(-ratio, ratio))), 3)


def provider_retry_delay(response: httpx.Response, attempt: int) -> float:
    base = 4.0 if response.status_code == 429 else 1.0
    fallback = min(30.0, base * (2 ** (attempt + 1)))
    retry_after = response.headers.get("retry-after", "").strip()
    if retry_after:
        try:
            seconds = float(retry_after)
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(retry_after)
                seconds = retry_at.timestamp() - time.time()
            except (TypeError, ValueError, OverflowError):
                seconds = None
        if seconds is not None:
            return _jittered(round(max(0.25, min(30.0, seconds)), 3))
    return _jittered(fallback)


def provider_transport_retry_delay(attempt: int) -> float:
    return _jittered(min(30.0, float(2 ** (attempt + 1))))
```

（`import random` 加在文件顶部；`random.seed()` 不调用——重试延时是墙钟行为，不影响评分确定性。）

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_providers.py -v`
Expected: 全部 PASS

- [ ] **Step 5: worker 传 turn 超时**

`apps/api/app/worker.py:378-387` candidate client 加 `timeout_seconds=settings.provider_turn_timeout_seconds`（当 >0；`ModelClient.__init__` 已有该参数，参照 judge client 用法 line 621）。

- [ ] **Step 6: 提交**

```bash
git add apps/api/app/runner/providers.py apps/api/app/worker.py apps/api/tests/test_providers.py
git commit -m "feat: status-class retry backoff with jitter and turn timeout"
```

### Task 10: Turn 生命周期事件

**Files:**
- Modify: `apps/api/app/runner/engine.py`（`run()` 205-246 与工具循环）
- Test: `apps/api/tests/test_engine.py`

- [ ] **Step 1: 写失败测试**

在 `apps/api/tests/test_engine.py` 末尾追加：

```python
def test_turn_boundary_events_emitted(tmp_path: Path, monkeypatch) -> None:
    scenario = load_scenario(SCENARIO_ROOT)
    prepared = PreparedScenario(
        scenario_root=SCENARIO_ROOT,
        workspace=tmp_path,
        metadata=scenario.metadata,
    )
    monkeypatch.setattr(engine_module, "SessionLocal", lambda: SimpleNamespace())
    engine = AgentEngine(
        run_id=uuid.uuid4(),
        client=FinalAnswerClient(),
        sandbox=SimpleNamespace(),
        prepared=prepared,
        faults=FaultController([]),
    )
    monkeypatch.setattr(engine, "_event", lambda kind, payload: engine.events.append({"kind": kind, **payload}))
    monkeypatch.setattr(engine, "_completion_gaps", lambda: [])
    monkeypatch.setattr(engine, "_compact_context", lambda *a, **k: None)
    engine.run(prepared)
    begins = [e for e in engine.events if e["kind"] == "run.turn.begin"]
    ends = [e for e in engine.events if e["kind"] == "run.turn.end"]
    assert len(begins) >= 1
    assert len(begins) == len(ends)
    assert all("turn" in e for e in begins + ends)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_engine.py::test_turn_boundary_events_emitted -v`
Expected: FAIL

- [ ] **Step 3: 实现**

`run()` 中 `_complete_model_turn` 调用处（205-210 行）包上 begin/end 事件：

```python
            turn_started = time.monotonic()
            self._event("run.turn.begin", {"turn": turn_number, "tool_calls": self.tool_calls})
            try:
                turn, provider_duration_ms = self._complete_model_turn(
                    messages,
                    tool_definitions,
                    turn_number=turn_number,
                )
            except HardResourceBudgetExceeded:
                self.hard_budget_reasons = ["provider_requests"]
                self._emit_hard_budget_event(self.hard_budget_reasons)
                final_response = (
                    "Hard Provider-request budget reached before the current "
                    "model turn could complete."
                )
                break
            self._event(
                "run.turn.end",
                {
                    "turn": turn_number,
                    "tool_calls": self.tool_calls,
                    "tool_call_count": len(turn.tool_calls),
                    "duration_ms": round((time.monotonic() - turn_started) * 1_000),
                    "input_tokens": turn.input_tokens,
                    "output_tokens": turn.output_tokens,
                },
            )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_engine.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add apps/api/app/runner/engine.py apps/api/tests/test_engine.py
git commit -m "feat: emit run.turn.begin/end lifecycle events"
```

### Task 11: 上下文压缩触发升级

**Files:**
- Modify: `apps/api/app/runner/engine.py`（`_compact_context` 712-769 与 run() 180-184 调用处）
- Test: `apps/api/tests/test_engine.py`

- [ ] **Step 1: 写失败测试**

在 `apps/api/tests/test_engine.py` 末尾追加：

```python
def test_compact_trigger_uses_token_estimate_when_chars_under_limit(tmp_path: Path, monkeypatch) -> None:
    scenario = load_scenario(SCENARIO_ROOT)
    prepared = PreparedScenario(
        scenario_root=SCENARIO_ROOT,
        workspace=tmp_path,
        metadata=scenario.metadata,
    )
    monkeypatch.setattr(engine_module, "SessionLocal", lambda: SimpleNamespace())
    engine = AgentEngine(
        run_id=uuid.uuid4(),
        client=FinalAnswerClient(),
        sandbox=SimpleNamespace(),
        prepared=prepared,
        faults=FaultController([]),
    )
    monkeypatch.setattr(engine, "_event", lambda kind, payload: engine.events.append({"kind": kind, **payload}))
    monkeypatch.setattr(engine, "_completion_gaps", lambda: [])
    compacted: list[str] = []
    monkeypatch.setattr(
        engine,
        "_compact_context",
        lambda messages, reason, target_characters: compacted.append(reason),
    )
    engine.token_usage_available = True
    engine.context_soft_characters = 100_000
    # 模拟字符数低于阈值但 token 估算超限
    engine.input_tokens = 90_000
    engine._compact_context_if_needed(
        [{"role": "user", "content": "x" * 40_000}],
        reason="token_estimate",
        soft_characters=100_000,
        target_characters=80_000,
    )
    assert compacted == ["token_estimate"]
```

（提示：若 `_compact_context` 原签名与调用方式不易拆分，可把触发判断提取为新方法 `_should_compact(estimated_tokens: int | None, characters: int, soft_characters: int) -> bool`，测试它更简单——按实际代码结构调整测试断言。）

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_engine.py::test_compact_trigger_uses_token_estimate -v`
Expected: FAIL（无 `_compact_context_if_needed`）

- [ ] **Step 3: 实现**

3a. 提取触发判断为纯方法：

```python
    def _should_compact(self, *, characters: int, estimated_tokens: int | None, soft_characters: int) -> bool:
        if characters >= soft_characters:
            return True
        if self.token_usage_available and estimated_tokens is not None:
            return estimated_tokens >= soft_characters // 4
        return False
```

3b. `run()` 180-184 的调用处改为：

```python
            estimated_tokens = None
            if self.token_usage_available:
                estimated_tokens = json_size(messages) // 4
            if self._should_compact(
                characters=json_size(messages),
                estimated_tokens=estimated_tokens,
                soft_characters=self.context_soft_characters,
            ):
                self._compact_context(
                    messages,
                    reason="token_estimate" if estimated_tokens and json_size(messages) < self.context_soft_characters else "soft_character_limit",
                    target_characters=self.context_target_characters,
                )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_engine.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add apps/api/app/runner/engine.py apps/api/tests/test_engine.py
git commit -m "feat: token-estimate aware context compaction trigger"
```

### Task 12: 工具返回结果优化（去重 + 结构化截断）

**Files:**
- Modify: `apps/api/app/runner/engine.py`（`__init__`、`_execute` 1173 附近、工具循环 422 处）
- Test: `apps/api/tests/test_engine.py`

- [ ] **Step 1: 写失败测试**

在 `apps/api/tests/test_engine.py` 末尾追加：

```python
def test_identical_read_result_deduplicated(tmp_path: Path, monkeypatch) -> None:
    scenario = load_scenario(SCENARIO_ROOT)
    prepared = PreparedScenario(
        scenario_root=SCENARIO_ROOT,
        workspace=tmp_path,
        metadata=scenario.metadata,
    )
    engine = AgentEngine(
        run_id=uuid.uuid4(),
        client=FinalAnswerClient(),
        sandbox=SimpleNamespace(),
        prepared=prepared,
        faults=FaultController([]),
    )
    first = engine._model_visible_result(
        ToolResult(call_id="r1", name="read_file", status="ok", output="A" * 5000)
    )
    assert first["output"] == "A" * 5000
    second = engine._model_visible_result(
        ToolResult(call_id="r2", name="read_file", status="ok", output="A" * 5000)
    )
    assert "Identical to tool call" in second["output"]
    assert second["truncated"] is True


def test_read_result_structured_truncation() -> None:
    scenario = load_scenario(SCENARIO_ROOT)
    prepared = PreparedScenario(
        scenario_root=SCENARIO_ROOT,
        workspace=Path("/tmp/x"),
        metadata=scenario.metadata,
    )
    engine = AgentEngine(
        run_id=uuid.uuid4(),
        client=FinalAnswerClient(),
        sandbox=SimpleNamespace(),
        prepared=prepared,
        faults=FaultController([]),
    )
    result = engine._model_visible_result(
        ToolResult(call_id="r1", name="read_file", status="ok", output="x" * 20_000)
    )
    assert result["truncated"] is True
    assert "[truncated" in result["output"]
    assert len(result["output"]) < 20_000
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_engine.py::test_identical_read_result_deduplicated tests/test_engine.py::test_read_result_structured_truncation -v`
Expected: FAIL（无 `_model_visible_result`）

- [ ] **Step 3: 实现**

3a. `__init__` 加：

```python
        self.tool_result_cache: dict[str, tuple[int, str]] = {}
        self.result_display_limit = 8_192
```

3b. 新增方法：

```python
    def _model_visible_result(self, result: ToolResult) -> dict[str, Any]:
        cache_key = f"{result.name}:{tool_call_signature(ToolCall(call_id=result.call_id, name=result.name, arguments=json.loads(result.model_dump_json(exclude={"output", "call_id"}).replace("{}", "{}"))) if False else result.call_id)}"
        # 简化：只读工具按 name 去重缓存（exec/write 等有副作用工具不参与）
        if result.name not in PARALLEL_SAFE_TOOLS:
            return result.model_dump(mode="json")
        signature = result.call_id  # 占位；实际在调用处传入 call signature
        return result.model_dump(mode="json")
```

（实现细节：去重逻辑放到调用点——工具循环里 `signature` 已知。把 `_model_visible_result(result, signature)` 实现为：对 safe 工具，若 `self.tool_result_cache.get(signature)` 存在且 output 相同 → 返回截断摘要；否则更新缓存。结构化截断：`_truncate_output(text, limit)` 实现 head 60% + `\n[truncated N bytes]...\n` + tail 40%，`truncated=True`。）

3c. 工具循环 422 行的 `messages.append(tool_message(call, result.model_dump_json(), native))` 改为：

```python
                visible = json.dumps(
                    self._model_visible_result(result, signature),
                    ensure_ascii=False,
                )
                messages.append(tool_message(call, visible, native))
```

（事件中的 `tool.result` 输出保持完整（现状），去重/截断只影响回灌给模型的文本——评分与归档保真不受影响。`tool.result` 事件 payload 增加 `deduplicated: bool` 与 `display_truncated: bool` 字段，供遥测。）

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_engine.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add apps/api/app/runner/engine.py apps/api/tests/test_engine.py
git commit -m "feat: dedupe identical read results and structured truncation"
```

**Phase 3 验收点**：`cd apps/api && uv run pytest tests/test_engine.py tests/test_providers.py -q` 全绿。

---

## Phase 4: 归档与导出优化

### Task 13: 遥测 bundle 与归档 schema v3

**Files:**
- Modify: `apps/api/app/telemetry.py`（`build_telemetry_bundle` 51-90）
- Modify: `apps/api/app/scenario/sdk.py`（`archive` 210-320）
- Test: `apps/api/tests/test_run_archival.py`、`apps/api/tests/test_telemetry.py`

- [ ] **Step 1: 写失败测试**

在 `apps/api/tests/test_telemetry.py` 末尾追加：

```python
def test_bundle_includes_budget_adjustments_and_turn_boundaries() -> None:
    from app.telemetry import build_telemetry_bundle

    events = [
        {"sequence": 1, "kind": "run.turn.begin", "turn": 1, "tool_calls": 0},
        {"sequence": 2, "kind": "run.budget_adjusted", "field": "hard_tool_calls", "new_value": 5000},
        {"sequence": 3, "kind": "run.turn.end", "turn": 1, "tool_calls": 2, "duration_ms": 100},
    ]
    bundle = build_telemetry_bundle(events)
    assert bundle["budget_adjustments"] == [events[1]]
    assert len(bundle["turn_boundaries"]) == 2
    assert bundle["schema_version"] >= 2
```

在 `apps/api/tests/test_run_archival.py` 追加（沿用该文件现有归档 fixture）：

```python
def test_archive_schema_v3_includes_new_telemetry_files(client, app, tmp_path) -> None:
    # 复用现有归档测试的 run + result 构造；断言 tar.gz 内存在
    # telemetry/budget-adjustments.jsonl、telemetry/turn-boundaries.jsonl、
    # resource-ledger.json、export.json，且 run.json["archive_schema_version"] == 3
    ...
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_telemetry.py tests/test_run_archival.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 telemetry**

`build_telemetry_bundle` 返回值加：

```python
    return {
        "schema_version": 3,
        ...
        "budget_adjustments": [
            event
            for event in normalized
            if event.get("kind") == "run.budget_adjusted"
        ],
        "turn_boundaries": [
            event
            for event in normalized
            if event.get("kind") in {"run.turn.begin", "run.turn.end"}
        ],
        "events": normalized,
    }
```

- [ ] **Step 4: 实现 sdk.archive**

`scenario/sdk.py` `archive()` 中：

4a. `detailed_payloads` 增加：

```python
            "telemetry/budget-adjustments.jsonl": jsonl_bytes(
                telemetry["budget_adjustments"]
            ),
            "telemetry/turn-boundaries.jsonl": jsonl_bytes(
                telemetry["turn_boundaries"]
            ),
            "resource-ledger.json": json_bytes(
                result.private_state.get("resource_ledger", {})
            ),
            "export.json": json_bytes(_lean_export(manifest_base)),
```

4b. `manifest["archive_schema_version"] = 3`；`archive_readme` 增加对应行。

4c. 新增 `_lean_export(manifest: dict) -> dict`（模块级函数，`archive` 内联也可）：返回精简导出 = 现有 manifest 字段的子集：`{export_schema_version: 3, platform_version, run, scenario, result 摘要, telemetry_summary, artifact_inventory, budget_adjustment_count, turn_summary, investigation_graph}`——不含 events 全文与 artifacts 内容。（`manifest_base` 为组装中的 manifest dict，注意在 `manifest` 完成前先构好 `export.json` 所需字段。）

- [ ] **Step 5: 运行测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_telemetry.py tests/test_run_archival.py -v`
Expected: 全部 PASS

- [ ] **Step 6: 提交**

```bash
git add apps/api/app/telemetry.py apps/api/app/scenario/sdk.py apps/api/tests/test_telemetry.py apps/api/tests/test_run_archival.py
git commit -m "feat: archive schema v3 with budget/turn telemetry and export.json"
```

### Task 14: 精简 JSON 导出（reports v3）+ `GET /runs/{id}/export`

**Files:**
- Modify: `apps/api/app/api/reports.py`
- Test: `apps/api/tests/test_reports.py`

- [ ] **Step 1: 写失败测试**

在 `apps/api/tests/test_reports.py` 末尾追加：

```python
def test_report_v3_compact_events_and_lean_fields(client, app) -> None:
    run = <按现有方式创建含工具事件的 run>
    response = client.get(f"/api/v1/reports/{run.id}")
    payload = response.json()
    assert payload["export_schema_version"] == 3
    tool_calls = [e for e in payload["events"] if e.get("kind") == "tool.call"]
    if tool_calls:
        assert "arguments" not in tool_calls[0]
        assert "arguments_sha256" in tool_calls[0]
    assert "turn_summary" in payload
    assert "budget_adjustments" in payload


def test_report_v3_full_events_query_param(client, app) -> None:
    run = <同上述>
    response = client.get(f"/api/v1/reports/{run.id}?include=full-events")
    payload = response.json()
    tool_calls = [e for e in payload["events"] if e.get("kind") == "tool.call"]
    if tool_calls:
        assert "arguments" in tool_calls[0]


def test_export_endpoint_formats(client, app) -> None:
    run = <同上述>
    response = client.get(f"/api/v1/runs/{run.id}/export?format=json")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["export_schema_version"] == 3
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_reports.py -v`
Expected: FAIL

- [ ] **Step 3: 实现**

3a. `reports.py` 增加紧凑事件工具函数：

```python
import hashlib


def _compact_events(events: list[dict]) -> list[dict]:
    compacted = []
    for event in events:
        item = dict(event)
        if event.get("kind") in {"tool.call", "tool.result"}:
            for key, payload_key in (("arguments", "arguments"), ("output", "output")):
                if key in item:
                    raw = item.pop(key)
                    if isinstance(raw, str):
                        encoded = raw.encode()
                        item[f"{payload_key}_sha256"] = hashlib.sha256(encoded).hexdigest()
                        item[f"{payload_key}_size_bytes"] = len(encoded)
                        item[f"{payload_key}_preview"] = raw[:200]
        compacted.append(item)
    return compacted
```

3b. `export_report` 增加 `include: str = "compact"` query 参数；`"export_schema_version": 3`；`"events"` 用 `_compact_events(telemetry["events"])`（`include != "full-events"` 时）；新增：

```python
        "budget_adjustments": [
            {"count": len(telemetry["budget_adjustments"]),
             "first_at": ...,
             "last_at": ...}
        ],
        "turn_summary": {
            "total": len(telemetry["turn_boundaries"]) // 2,
            "average_duration_ms": ...,
            "max_duration_ms": ...,
        },
```

（预算调整"摘要级"：只给计数与时间范围，不给完整载荷。）

3c. 新端点（`reports.py` 或 `runs.py`）：

```python
@router.get("/{run_id}/export")
def export_archive(
    run_id: uuid.UUID,
    format: str = "json",
    include: str = "all",
    session: Session = Depends(get_session),
    user: UserAccount = Depends(current_user),
) -> Response:
    run = session.get(BenchmarkRun, run_id)
    if not can_access_run(session, user, run):
        raise HTTPException(status_code=404, detail="Run not found")
    if format == "json":
        return export_report(run_id, include=("full-events" if include == "all" else include), session=session, user=user)
    if format != "tar.gz":
        raise HTTPException(status_code=400, detail="format must be json or tar.gz")
    archive_path = Path(get_settings().artifact_root) / f"{run_id}.tar.gz"
    if not archive_path.exists():
        raise HTTPException(status_code=404, detail="No run archive available")
    if include == "all":
        return FileResponse(archive_path, media_type="application/gzip", filename=archive_path.name)
    # include 逗号分隔过滤打包：events/telemetry/diffs/graph
    allowed = set(part.strip() for part in include.split(","))
    path_markers = {
        "events": ["events.jsonl"],
        "telemetry": ["telemetry/"],
        "diffs": ["artifacts/"],
        "graph": ["investigation/"],
    }
    keep = []
    for marker_name, markers in path_markers.items():
        if marker_name in allowed:
            keep.extend(markers)
    if not keep:
        raise HTTPException(status_code=400, detail="No matching archive content")
    buffer = io.BytesIO()
    with tarfile.open(archive_path, "r:gz") as source:
        with tarfile.open(fileobj=buffer, mode="w:gz") as out:
            for member in source.getmembers():
                if member.isfile() and any(member.name.startswith(marker) for marker in keep):
                    out.addfile(member, source.extractfile(member))
    buffer.seek(0)
    return Response(
        buffer.getvalue(),
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="run-{run_id}-filtered.tar.gz"'},
    )
```

（路由注意：`/runs/{run_id}/export` 放在 runs router 而不是 reports router；`export_report` 的签名调用处调整。`main.py` 无需改动，runs/reports router 已注册。）

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_reports.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add apps/api/app/api/reports.py apps/api/app/api/runs.py apps/api/tests/test_reports.py
git commit -m "feat: lean report v3 with compact events and export endpoint"
```

### Task 15: 导出中心 UI

**Files:**
- Modify: `apps/web/src/lib/api.ts`
- Modify: `apps/web/src/App.tsx`（底部导出按钮区 2475-2540）
- Modify: `apps/web/src/styles.css`

- [ ] **Step 1: API 封装**

`api.ts`：

```ts
  exportUrl: (runId: string, format: "json" | "tar.gz", include: string[]) => {
    const params = new URLSearchParams({ format });
    if (format === "tar.gz" && include.length > 0) {
      params.set("include", include.join(","));
    }
    return `${API_BASE}/runs/${runId}/export?${params.toString()}`;
  },
```

- [ ] **Step 2: 实现导出中心**

在 RunDetailPage 底部（替换"导出完整遥测"与"下载运行归档"两个按钮）实现 `ExportCenter` 区块：
- 格式选择：radio tar.gz / json
- 内容多选（仅 tar.gz 生效）：全量/遥测/事件/diff/图谱 checkboxes，默认"全量"
- 清单预览：复用 run artifacts 数据（已有 `data.artifacts` 或 artifacts query），展示 name/size/sha256
- 下载：`<a href={api.exportUrl(...)} download>` 链接（`window.open` 也行，保持现有下载交互模式）
- 样式用现有卡片/按钮 class

- [ ] **Step 3: 运行 lint 与测试**

Run: `cd apps/web && pnpm lint && pnpm test`
Expected: PASS

- [ ] **Step 4: 提交**

```bash
git add apps/web/src/lib/api.ts apps/web/src/App.tsx apps/web/src/styles.css
git commit -m "feat: export center UI with format and content selection"
```

**Phase 4 验收点**：`cd apps/api && uv run pytest tests/test_reports.py tests/test_run_archival.py tests/test_telemetry.py -q` 全绿；`pnpm lint` 通过。

---

## Phase 5: 收尾

### Task 16: 版本、CHANGELOG、文档、全量回归

**Files:**
- Modify: `VERSION`（0.13.0 → 0.14.0）
- Modify: `CHANGELOG.md`
- Modify: `docs/architecture.md`（新增"归档契约"章节：schema v3 目录结构、export.json 字段、budget_overrides 机制、overtime 扣分规则）
- Modify: `docs/superpowers/specs/2026-08-05-budget-harness-diff-archive-design.md`（实现状态勾选，如需要）

- [ ] **Step 1: 更新 VERSION 与 CHANGELOG**

`VERSION` → `0.14.0`；CHANGELOG 按现有格式追加 v0.14.0 条目（预算动态调整、diff 页面、harness 优化、归档 schema v3 与导出中心）。

- [ ] **Step 2: 全量回归**

```bash
cd apps/api && uv run ruff check . ../../scenarios
cd apps/api && uv run pytest
cd apps/web && pnpm lint
cd apps/web && pnpm test
./scripts/check-version.sh
```

Expected: 全部通过

- [ ] **Step 3: 沙箱 CI 冒烟（若本机 rootless docker 可用）**

```bash
make preflight && make sandbox && make sandbox-smoke
```

- [ ] **Step 4: 提交**

```bash
git add VERSION CHANGELOG.md docs/architecture.md
git commit -m "release: v0.14.0 platform maintenance"
```

---

## Self-Review 备注（实现前请核对）

1. `engine.py` 中所有 `self.prepared.metadata.budget` 引用点（Task 2）务必用 `rg` 扫净，遗漏会导致热更新不生效。
2. Task 8 的 `flush()` 中 futures 收集写法在实现时优先用 `{future: call for call in pending}` 字典按声明序取结果，避免测试里的临时 hack；事件/状态机推进必须全部留在主线程。
3. Task 12 去重缓存键 = `tool_call_signature(call)`（已含参数哈希）；`_model_visible_result` 需要拿到 signature，实现时从工具循环传入。
4. Task 14 的 `export_report` 签名变化会破坏既有调用（runs.py export 端点调用它）——实现时统一改为 kwargs 调用。
5. 旧 scorecard 无 `overtime_penalty` 字段：前端渲染需容错（`scorecard.overtime_penalty ?? null`）。
