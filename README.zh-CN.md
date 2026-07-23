# The Evil Repository

[English](README.md) | [简体中文](README.zh-CN.md)

> 一个面向长时程 AI 软件工程 Agent、故意制造证据敌意并采用容器隔离的基准测试。

The Evil Repository 会把模型扔进一场刻意腐烂的软件事故：两个相互引用的
Git 仓库、彼此矛盾的文档、损坏的 CI 预言机、Prompt Injection、可复现的
工具故障、过时的 SQLite 缓存，以及塞满脏数据的生产风格 PostgreSQL 快照。
模型必须找出真正的回归原因，提交最小且正确的补丁，并给出可以审计的证据报告。

它不只评价「Bug 最后修没修好」，还分析 Agent 如何建立和推翻假设、如何选择
证据、是否被虚假权威误导、如何从工具故障中恢复，以及是否守住安全边界。因此，
它更接近 AI Agent CTF、事故响应 Benchmark 与 Agent 行为分析平台的结合体。

产品采用本机优先架构：React 数据控制台由 FastAPI 提供后端。每个
「候选模型 × 任务」组合都会得到一个全新的 Rootless Docker 工作区。候选容器
没有网络、没有 Docker socket、没有宿主机绑定挂载，也拿不到任何模型 Provider
凭据。

## 当前状态

项目正在积极开发。第一个版本聚焦于标准「终焉仓库」挑战，并打通完整的执行、
遥测、评分、行为分析和可视化链路。

当前控制平面支持四种明确的模型协议：

- OpenAI Responses API；
- Anthropic Messages API；
- OpenAI-compatible Chat Completions；
- Ollama Chat。

「OpenAI-compatible」与「OpenAI Responses」是两种不同协议，不能混为一谈。
Runner 会把它们各自的消息、工具调用和 Token 用量转换成统一的内部格式。

## 快速开始

环境要求：

- Linux 与 Rootless Docker / Docker Compose；
- Node.js 22+ 与 pnpm；
- Python 3.12+ 与 uv。

```bash
cp .env.example .env
# 如果本机 uid 不是 1000，请修改 .env 中的 ROOTLESS_DOCKER_SOCKET。
make preflight
make bootstrap
make sandbox
docker compose up --build
```

然后打开 `http://127.0.0.1:5173`。

WebUI 默认使用简体中文，可以从右上角切换到英文。UI 和 API 默认只监听回环
地址；不要把开发环境直接暴露给不可信网络。

## 仓库结构

```text
apps/web/                  React/TypeScript 控制台
apps/api/                  FastAPI API、Worker、Runner 与评分器
scenarios/                 版本化 Scenario SDK 包与合成题目语料
infra/sandbox/             无网络候选环境镜像
docs/                      架构、威胁模型与场景编写文档
```

完整开放设计见 [`DESIGN.zh-CN.md`](DESIGN.zh-CN.md)，英文版见
[`DESIGN.md`](DESIGN.md)。设计文档属于开源项目本身，并非内部规划附件；涉及
架构的 Pull Request 应同时更新中英文设计。

延伸阅读：

- [`docs/architecture.md`](docs/architecture.md) — 实现结构与信任边界；
- [`docs/scenario-authoring.md`](docs/scenario-authoring.md) — 编写 Scenario SDK 包；
- [`docs/threat-model.md`](docs/threat-model.md) — 安全假设与剩余风险；
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — 本机开发与贡献规范；
- [`SECURITY.md`](SECURITY.md) — 负责任披露流程。

## 安全模型

Rootless Docker 是实用且较强的本机隔离边界，但共享内核容器不是对所有逃逸漏洞
的数学证明。Runner 始终把候选代码视为不可信内容，不挂载宿主机工作区，并在
跨边界传递归档与路径时执行验证。详见
[`docs/threat-model.md`](docs/threat-model.md)。

## 许可证

Copyright © 2026 The Evil Repository contributors.

项目采用 GNU Affero General Public License v3.0 only
（`AGPL-3.0-only`）。仓库内分发的原创合成 Benchmark 内容同样受此许可证约束，
除非具体文件另有声明。
