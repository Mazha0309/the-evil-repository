# v0.14.0 设计：预算动态调整 · Harness 优化 · Diff 页面 · 归档与导出优化

日期：2026-08-05
目标版本：0.14.0（当前 0.13.0）
分支：`agent/v0-14-platform-maintenance`

## 1. 背景与目标

平台（The Evil Repository）是仓库规模的 AI Agent 基准测试系统。当前存在四个痛点：

1. **预算不可变**：8 个预算字段（软/硬 × 秒/工具调用/Provider 请求/Token）在运行创建时冻结。硬预算耗尽直接终止并右删失，无法在运行中调整，强模型常被硬限制卡死（历史：GPT-5.6 Sol / Grok 4.5 均被 60 分钟硬限制终断）。
2. **Runner 主循环串行、重试策略单一**：工具调用严格串行执行；Provider 重试退避固定；生命周期粒度粗糙；上下文压缩仅按字符数触发；重复工具输出全文回灌浪费 token。
3. **无 Diff 查看能力**：候选仓库改动（`artifacts/*.diff` + `*.status`）只存在于归档 tar.gz 中，前端无任何展示。
4. **归档与导出原始**：归档结构无 schema 契约、缺预算调整历史/turn 边界/资源账本/报告缺 diff 全文；导出只有两个零散按钮，无格式与内容选择。

目标：v0.14.0 内按序交付 预算动态调整 → Diff 页面 → Harness 优化 → 归档与导出优化。四者均深度触碰 `engine.py`，串行实现、每步独立验收。

## 2. 现状关键事实（探索结论）

- 预算定义：`apps/api/app/challenge/spec.py` `BudgetSpec`（8 字段，soft<hard 校验）；场景默认在 `scenarios/*/metadata.yaml: budget:`；运行级覆盖在 `RunCreate`（`schemas.py`）；运行时合并于 `worker.py:316-345`（`model_copy(update=...)` 覆盖到 `prepared.metadata.budget`）。
- 主循环：`apps/api/app/runner/engine.py` `AgentEngine.run()`（130-471 行），循环条件 `while tool_calls < hard_calls and _active_elapsed() < hard_seconds`；硬预算耗尽 → break → `run.hard_budget_exceeded` 事件 + `private_state` 携带 `hard_budget_reasons`。
- 评分：`apps/api/app/scoring.py`（效率维度线性插值，`call_budget_points`）；场景侧 `scenarios/*/grading/hidden.py` 写 `outcome.status = budget_exhausted, censored=True`。
- 校准：`CalibrationPolicy`（`scenario/sdk.py:43-49`）`exclude_budget_exhausted=True`；dashboard 平均分只统计未 censored run。
- 运行通信：暂停/恢复走 `config.pause_requested` DB 字段 → engine 轮询（`runs.py:338-343`、engine `_wait_for_resume`）。预算热更新复用同一机制。
- 工具：协议定义 `runner/protocol.py` `TOOL_DEFINITIONS`；执行分发 `engine._execute`（1113-1250 行）+ `sandbox.py` `DockerSandbox.execute`（文件/命令/隐藏验证）+ 状态机（incident/release/observability）。
- Provider：`runner/providers.py` `ModelClient.complete` 按 profile 分发；`_post`（746-860 行）已有 `RETRYABLE_PROVIDER_STATUS={408,425,429,500,502,503,504}`。
- 上下文压缩：`engine._compact_context`（712-769 行）字符数触发，确定性 checkpoint 替换（`RUNNER_CONTEXT_CHECKPOINT_V1`），无 LLM 摘要。
- 事件：`app/events.py` `append_event()`（run_id, sequence 唯一约束）；`tool.call`/`tool.result` 事件已含 `call_signature_sha256`（重复调用检测，`engine.py:2175-2192`）。
- 归档：`scenario/sdk.py` `Scenario.archive`（210-320 行）→ `{run_id}.tar.gz`（run.json + events.jsonl + telemetry/* + investigation/ + artifacts/index.json + artifacts/*，含完整性 sha256）；artifact 注册 `RunArtifact`（worker.py）。
- 前端：SPA 单文件路由（`apps/web/src/App.tsx` 3865 行），RunDetailPage（1999-2578 行）5 个 tab：`live/overview/graph/audit/score`；底部有"导出完整遥测"（`api.reportUrl`）与"下载运行归档"（`api.runArtifactUrl`）两个按钮；无 diff UI、无 diff 类型。
- 报告导出：`apps/api/app/api/reports.py`（schema v2），artifacts 只含元数据不含内容。

## 3. 功能一：预算动态调整

### 3.1 运行期热更新

- **通信机制**：复用 pause 模式。API 写入 `run.config.budget_overrides`（追加，不可删除，只审计追加），engine 主循环每轮开始检查未应用项并应用到运行时预算。
- **事件**：每次应用发 `run.budget_adjusted` 事件：`{field, old_value, new_value, reason, requested_by, applied_at}`。
- **校验**（API 层）：8 字段必须过 `BudgetSpec` 校验（soft<hard、可选对必须成对）；antigravity provider 继续禁止 token 预算；仅运行中（running/preparing 阶段）可调；权限与暂停/恢复一致。
- **调小语义**：允许调小；调小后若已超新硬限制，按正常预算终止流程结束（下一轮循环条件自然退出）。
- **运行时预算 = 仓库默认 + 运行配置覆盖 + 热更新覆盖**（engine 主循环判断终止只用运行时预算）。

### 3.2 censored 与扣分（统一基准 = 仓库默认预算）

- **仓库默认预算** = task manifest 的 `budget`（`TaskDefinition.manifest`），永不被运行覆盖与热更新污染，作为评分基准。
- **censored 判定**（评分时）：任一维度最终实际用量 > 对应仓库默认硬预算 → `outcome.status=budget_exceeded, censored=True`，`hard_budget_reasons` 含 `exceeded_default_budget`（兼容 `run_outcomes.py` 推断层）。提前调大但最终未超默认 → 不 censored，可参与校准。
- **线性超额扣分**（`scoring.py` 新维度 `overtime_penalty`，进 scorecard）：
  - 对默认硬预算非空的每个维度：`overrun_d = max(0, final_d − default_hard_d) / default_hard_d`
  - `penalty = Σ min(overrun_d, cap_d) × weight_d`
  - 默认 `cap_d = 2.0`（超 200% 封顶），`weight_d`：时间 30、工具调用 30、Provider 请求 15、Token 15（全局配置可调，先硬编码默认进 config）
  - 总分下限不为负（`max(0, score − penalty)`）；扣分明细（每维度 overrun/weight/penalty）写入 scorecard。
- 遥测：`resource-ledger.json` 增加 `default_budget` 对比列。

### 3.3 UI

- 运行详情页 + LiveRunMonitor 加"调整预算"按钮（运行时可见；权限同暂停/恢复）。
- 弹窗：8 字段当前（运行时）值，可改，reason 必填；提交后展示已应用的调整历史（来源 `run.budget_adjusted` 事件）。

### 3.4 边界

- 已结束 run 不可调。
- 调整不改变已产生事件与已用资源；只影响未来行为与最终评分基准对比。
- 软预算警告/finalization nudge 在热更新后按新阈值重新计算（现有 `_soft_budget_warning`/`_finalization_nudge` 的阈值读取改为动态）。

## 4. 功能二：Diff 页面

### 4.1 API

- `GET /api/v1/runs/{id}/diffs`：
  - 优先读运行归档 tar.gz 中 `artifacts/*.diff` + `*.status`；无归档时读 failure-checkpoint。
  - 返回 `[{repo, diff_text, status_text, added_lines, removed_lines, file_count}]`（added/removed/file_count 由服务端解析 unified diff 得出）。
  - 归档缺失 → 404 + 错误信息。

### 4.2 前端

- RunDetailPage 新增 `diff` tab（tab union 增加 `"diff"`）。
- `DiffViewer` 组件：
  - 顶部仓库切换（dead-letter / palimpsest）+ `+X −Y` 统计 + `git status` 摘要。
  - 统一 diff 解析（`diff --git`/`---`/`+++`/`@@`/`± ` 行），按文件折叠展开。
  - 纯 CSS 渲染（+/-/上下文着色 + 行号），不引第三方高亮库。
  - 单文件改动 >500 行时分页/折叠。
- `api.ts` 加 `runDiffsUrl`；`types.ts` 加 `RunDiff` 类型。

## 5. 功能三：Harness 优化（学习 Codex）

### 5.1 并行工具调用

- `protocol.py` 工具 schema 加 `parallel_safe` 标记（schema 元数据，不进模型可见描述）：read_file / list_files / browser_* / record_hypothesis / record_evidence / link_evidence / 可观测性只读工具为 safe；write_file / exec_command / incident_* / release_* / faults 注入点为非 safe。
- 引擎同轮内 safe 工具并发执行（限流 4），**结果按声明顺序归位**，事件顺序与内容与串行一致（benchmark 确定性不破坏）。非 safe 工具保持串行，且等待前序 safe 组完成。
- 执行机制：引擎核心保持同步，工具执行走线程池（IO 密集）。调用链 `_execute` → safe 组收集 → 并发 → 结果按序。

### 5.2 弹性重试/退避

- `providers.py` `_post` 升级：指数退避 + 全抖动（jitter），按状态分类：429 基数大、5xx/网络错误基数小；每次重试照旧计入 provider 请求预算与 `on_retry` 事件。
- `max_retries`、退避基数、上限做成 provider profile 可配置字段（默认值兼容现状），`model_profiles.py` API + 前端模型参数表单同步（可后置，见 5.7）。

### 5.3 Turn 粒度生命周期

- 显式 Turn 定义：一次 provider 请求 + 其工具执行 + 结果。
- 事件链加 `run.turn.begin/end`（含 turn 序号、耗时、tool call 数、token）。
- 暂停/恢复/取消检查与单 turn 超时 watchdog 按 turn 边界执行；turn 超时（如 provider 请求超过配置秒数）触发弹性重试或终止（可配置）。

### 5.4 上下文压缩升级

- 触发条件从纯字符数升级为：字符数 + token 估算（provider 支持 token 用量时按历史 token/字符比估算）。
- **保持确定性压缩**：不做 LLM 摘要（非确定性会破坏 benchmark 可复现性，与 Codex 的取舍刻意不同）。分级压缩（soft→target→emergency）沿用，阈值可配置。

### 5.5 工具返回结果优化

- **内容寻址去重**：同签名工具调用（`call_signature_sha256` 已存在）结果缓存；重复时返回摘要"结果与第 N 次相同 + 截断内容"而非全文。
- **结构化截断**：超限输出 head+tail 保留 + 中间省略标记，附截断统计（已截断字节/行数）进 tool.result 事件。

### 5.6 事件追踪对齐

- 补齐事件链关联：`tool.call`/`tool.result` 用同一 `call_id` 关联；turn 边界事件；预算调整事件；压缩事件携带触发原因与保留块数。

### 5.7 范围裁剪

- Provider 退避参数进 profile 的 UI 表单（模型参数）属可选后置项；若拖慢交付，先 API+引擎支持，UI 表单放 v0.14.1。本版本内引擎与配置层必须完整。

## 6. 功能四：归档与导出优化

### 6.1 结构规范化

- 归档内 telemetry 子文件统一 `schema_version` 头（每个 json/jsonl 首字段）+ 字段命名随 run.json 现有 snake_case 约定。
- 目录契约写入 `docs/architecture.md`（新增"归档契约"章节）。

### 6.2 内容补全

- 归档新增（sdk.archive 扩展）：
  - `telemetry/budget-adjustments.jsonl`（热更新历史）
  - `telemetry/turn-boundaries.jsonl`（turn 摘要）
  - `resource-ledger.json`（现状在 private_state，未进归档）
  - `artifacts/*.diff` 全文已在归档（保持），报告 JSON 补 diff 全文。
- 报告导出（reports.py）升级 schema v3：补 `diffs`（全文）、`budget_adjustments`、`turn_summary`、`overtime_penalty` 明细。

### 6.3 导出中心 UI

- 运行详情页新增"导出中心"（替代现有底部两个零散按钮）：
  - 格式：规范化 tar.gz / 单文件 JSON
  - 内容：全量 / 遥测 / 事件 / diff / 图谱（多选；tar.gz 按内容过滤打包）
  - 归档清单预览（文件名 + 大小 + sha256）+ 一键下载
- API：`GET /runs/{id}/export?format=&include=`（复用完整性哈希逻辑）。

## 7. 数据与兼容

- `run.config.budget_overrides`：新字段，向后兼容（旧 run 无此键）。
- `reports.py` schema v2 → v3：旧 v2 消费者（如有）需注意；`export_schema_version` 字段递增。
- 评分：`overtime_penalty` 新维度进 scorecard，旧 scorecard 无此字段 → `normalize_scorecard_outcome`/前端渲染需容错。
- censored 判定从"硬预算触发"扩展为"最终用量超默认预算"：`run_outcomes.py` 兼容层同步扩展；dashboard 平均分逻辑不变（仍排除 censored）。
- 归档契约变更 → `scenario/sdk.py` 归档版本号递增（run.json 内）。

## 8. 测试策略

- 后端 pytest（apps/api/tests 现有风格）：
  - 预算：热更新应用、事件、调小触发终止、censored 判定（超/不超默认）、扣分公式边界（0 超额、cap 封顶、总分为负钳位）。
  - 并行工具：事件序与串行一致、限流、非 safe 串行。
  - 退避重试：429/5xx 分类、重试计数入预算。
  - diff 端点：解析统计、归档缺失 404。
  - export：格式/内容过滤、完整性哈希。
- 前端 vitest：DiffViewer 解析单测、导出中心类型。
- 回归：跑现有 CI workflow（api lint/test、web lint/test、rootless sandbox-image 构建）。

## 9. 交付顺序（串行）

1. 预算动态调整（engine + scoring + API + UI + 测试）→ 验收
2. Diff 页面（API + 前端 + 测试）→ 验收
3. Harness 优化（并行/退避/turn/压缩/去重/事件）→ 验收
4. 归档与导出优化（sdk + reports + export API + 导出中心 UI）→ 验收
5. 全量回归 + CHANGELOG + 版本号 → 合并

## 10. 明确不做（YAGNI）

- 运行间 diff 对比、LLM 摘要压缩、自动延长弹窗、预算调小的历史回滚、导出中心增量下载/断点续传。
