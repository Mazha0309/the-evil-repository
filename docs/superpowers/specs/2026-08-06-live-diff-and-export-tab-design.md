# v0.14.1 设计：实时 Diff 与导出独立 Tab

日期：2026-08-06
目标版本：0.14.1
分支：从 main（b40fe87）新建

## 1. 背景与问题

- **Diff 页无实时性**：v0.14.0 的 diff tab 只读归档 tar.gz（`GET /runs/{id}/diffs`），运行中/被取消/无归档的 run 全部无法查看，与"opencode 能实时看到 agent 改动"的预期不符。
- **导出入口**：导出中心埋在 RunDetailPage 底部，与 tab 结构不统一。

## 2. 实时 Diff

**数据链路**：沙箱已有 `git_diff(repo)`/`git_status(repo)`（sandbox.py:662-698，collect_artifacts 复用）→ engine 在修改性工具（write_file/exec_command 成功）后的 **turn 结束点**采集两个候选仓库（dead-letter/palimpsest）的 diff + status → 发 `run.repo_diff` 事件进事件流 → 前端 diff tab 从事件流实时渲染（事件流已有 1-3s 轮询，无需新轮询）。

**事件 schema**（`run.repo_diff`，每仓库一条）：
```json
{
  "kind": "run.repo_diff",
  "repo": "dead-letter",
  "diff_text": "...",        // git diff --no-ext-diff HEAD --
  "status_text": "...",      // git status --porcelain=v1
  "added_lines": 1, "removed_lines": 2, "file_count": 1,  // 复用 diffs.py _stats
  "updated_at": "2026-08-06T..."
}
```

**采集策略**：
- 触发：turn 内任一 write_file/exec_command 成功（`_process_tool_result` 内标记 dirty），turn 结束统一采集一次（避免轮内多次全量 diff）
- 两个 repo 串行 `git_diff` + `git_status`（各 30s timeout、1MB 上限，沿用沙箱既有参数）
- 采集失败：静默跳过该 repo（logger.debug），不打断主循环
- 事件体积：diff 可能数 MB（max 1MB×2）——DB TEXT 列可承受；事件流 refetch 每次拉新事件，体积 OK

**前端**：
- DiffTab 双数据源：事件流中的最新 `run.repo_diff` 事件优先（实时路径）；事件流无该事件（旧 run/归档 run）时 fallback `GET /runs/{id}/diffs`（归档路径，现状保留）
- DiffViewer 输入结构不变（RunDiff[]）

**兼容**：旧 run 无 repo_diff 事件 → 自动走归档路径；新 run 归档后事件流里仍有最终 diff（与归档 diff 一致）

## 3. 导出独立 Tab

- RunDetailPage tab union 加 `"export"`；tab 按钮（Download 图标，双语文案"导出 / Export"）
- 导出中心 section 从页面底部移到 `{tab === "export" && ...}` 内容区；state 与组件不动
- 行为变化：运行中需要导出需切到 export tab（可接受）

## 4. 测试

- engine：write_file 成功后 turn 结束发 run.repo_diff 事件（fake sandbox 提供 git_diff/git_status 返回），无修改工具时不发
- 采集失败静默：git_diff 抛异常 → 不发事件、主循环继续
- 前端：DiffTab 事件流优先路径（mock 事件流含 repo_diff → 渲染）；无事件 fallback 路径
- 导出 tab：类型/渲染冒烟

## 5. 明确不做（YAGNI）

- 逐文件级实时 diff 推送（事件已含全量 diff，前端可折叠）、diff 历史时间线（仅最新态）、沙箱内 git blame
