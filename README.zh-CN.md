# The Evil Repository

[English](README.md) | [简体中文](README.zh-CN.md)

> 一个以证据为基础、采用容器隔离、面向仓库级 AI 软件事故响应的基准测试。

The Evil Repository 用仓库级、确定但充满不确定性的生产事故，评估 AI Agent
如何调查真实工程问题。环境包含相互引用的 Git 仓库、彼此矛盾的运行证据、损坏
的 CI 预言机、间歇症状、幽灵告警、Prompt Injection、脚本化工具故障、数据库
历史和受约束的生产动作。Agent 必须先证明什么是真的、保留哪些约束、如何控制
风险，然后才提交最小且经过验证的修复与可审计证据报告。

它位于仓库级软件工程 Benchmark、事故响应模拟器与 Agent 行为分析平台之间。
一次运行除了确定性的 1,200 分场景 Scorecard，还会产出 Hypothesis / Evidence
Graph、行为画像、离散错误统计、资源账本、Agent 执行图和调查过程回放。

产品采用本机优先架构：React 数据控制台由 FastAPI 提供后端。每个
「候选模型 × 任务」组合都会得到一个全新的 Rootless Docker 工作区。候选容器
没有网络、没有 Docker socket、没有宿主机绑定挂载，也拿不到任何模型 Provider
凭据。

## 当前状态

平台当前版本为 **v0.8.0**，仍在积极开发，发布记录见
[`CHANGELOG.md`](CHANGELOG.md)。本版包含标准「终焉仓库」挑战、账户隔离、
管理员控制台、服务器监控、实时 Agent 活动控制台，以及完整的执行、遥测、评分、
行为分析和可视化链路。

本版同时引入版本化 Suite 契约。仓库内置的「生产事故工程套件」目前只有
**一个公开开发场景、一个活跃题族**。其策略要求至少 20 个场景引用、五个活跃
题族，并包含三个 held-out 题族后，才允许宣称具备排行榜资格。WebUI 与
`/suites` API 会如实显示 `1/5`、`0/3`、`1/20`。因此当前版本适合做深入工程
分析，但**还不是统计上有效的通用模型总榜**。

长时间调查可以在 Provider/工具安全边界暂停并继续，不会丢弃候选工作区或对话；
暂停时间不消耗配置的硬运行预算。暂停状态仍由当前 Runner 进程保管，并不意味着
运行可以跨 Runner 重启恢复。

当前控制平面支持四种明确的模型协议：

- OpenAI Responses API；
- Anthropic Messages API；
- OpenAI-compatible Chat Completions；
- Ollama Chat。

「OpenAI-compatible」与「OpenAI Responses」是两种不同协议，不能混为一谈。
Runner 会把它们各自的消息、工具调用和 Token 用量转换成统一的内部格式。

模型配置创建后可以继续编辑，已有 API Key 无需重新输入，留空即保留原密钥。
中英双语参数面板可配置温度、Top P、最大输出 Token、推理/思考挡位与服务挡位，
并按所选协议映射到正确字段。兼容服务的额外字段可以通过有大小限制的高级 JSON
填写，但凭据、Header、Prompt、模型 ID、工具声明与传输字段会被拒绝；Runner
在每次真正构造请求时还会再次强制保护这些核心字段。

Runner 现在可同时执行多次彼此独立的测试，默认提供两个槽位。管理员可以在后台
把并发数动态调整到 1–16，无需重启，也不会终止已经在跑的任务；
`RUNNER_CONCURRENCY` 只负责设置全新数据库的初始值。每个槽位仍有独立 UUID、
容器、tmpfs 工作区、模型对话、故障状态和归档，管理员监控面板会显示「已用槽位 /
总槽位」。取消运行会清理无法恢复的对话与临时工作区，因此 WebUI 必须先明确
二次确认。

可选的独立 LLM 语义裁判现已真正接入：确定性评分结束后，Runner 会调用所选
裁判 Provider，分别评价因果一致性、证据支撑、假设演化、决策/风险推理与报告
可复现性，生成单独的 0–100 分。它绝不会改动 1,200 分主榜。裁判看不到候选
身份，必须引用版本化审计 Ref，候选报告和事件文本都会被明确标成不可信数据；
格式错误最多重试一次。Provider 或 Schema 失败只会标记语义评审失败，不会让
整次 Benchmark 作废。

选择语义裁判意味着控制平面会把限长评审包发送给该模型配置对应的 Provider。
如果运行报告可能含有无权向外部服务披露的数据，就不要选择外部 Provider。

## Benchmark 契约

系统明确分为三层：

1. 版本化 Suite Manifest，负责组织独立题族及 development、validation、
   held-out 划分；
2. 版本化的 Scenario SDK 目录包，包含仓库、数据库、注入、确定性故障、离线
   Browser 语料、隐藏真相、评分规则与元数据；
3. 与具体题目无关的 Runner，统一执行
   `load → prepare → run → grade → archive`，React 只读取标准化结果。

私有真相采用由原因、条件、症状、约束、不变量和修复组成的 Truth Graph。一个
场景可以声明多条可接受的解决路径，例如经过验证的向前修复或安全回滚，并为每条
路径绑定客观隐藏检查。判定器会保留部分因果覆盖率，但不会把残缺证据伪装成通过。
当前「终焉仓库」3.0.3 继续沿用 3.0.2 的真相与生成事故结构，只通过新版本记录
重新校准的 30/60 分钟执行包络；多路径契约提供给后续题族使用，不会在不升级
场景版本的情况下偷偷改动已发布真相。

标准题刻意消除「看一个文件、跑一个测试、改一行就结束」的捷径。真实回归被埋在
大量后续 Git 历史之前；README、Issue、注释、TODO、日志、CI 输出、数据库描述与
Browser 结果互相冲突；第二个仓库与关键提交提供独立来源；在线 PostgreSQL 状态又
与过期 SQLite 缓存不一致。离线互联网只能通过 `browser.search`、
`browser.open`、`browser.find` 使用，候选模型不能通过遍历复制到工作区的
Mirror 目录绕过 Browser 行为评测。

场景 3.0.3 让规模本身进入有效调查面：五条真实中继链包含 704 个不透明执行
Cell，七个独立损坏必须同时修复，修六个仍然失败。双仓库精确包含 5,000 个跟踪
文件、2,000 次提交、40 个语义托管 Checkpoint、七道客观推理门、新旧依赖冲突、
一个未知恢复二进制、损坏缓存，以及约 100 MiB 离线材料。所有关键过渡都会修改
真实行为，命名分支只是互相冲突的部分导出，不是 Golden Snapshot。

可信且确定的 Incident Director 另外提供八张实时票据：一个真实间歇回归、一个
相关症状、虚假性能与认证告警、只属于历史快照的脏数据、环境漂移、权限陷阱，
以及一个真实但不属于当前事故的 2038 风险。所有生产观察和动作都经项目工具
中转，推进逻辑回放时钟，并改变 SLO、错误预算、数据完整性、风险与回滚状态，
但永远不暴露 Docker 或宿主机。「不改」「保留」「拒绝」「延期」都可能是正确答案。

后续场景还可以显式启用 `ps`、`systemctl`、`journalctl`、`lsof`/socket 检查、
`strace` 与 `perf` 的确定性项目中转等价工具。它们只观察模拟事故状态，绝不附加
真实宿主机进程或暴露真实网络包；采集器、时钟域、有效信号和干扰项都可重放。
「终焉仓库 3.0.3」保持冻结，不会被追加入这些新工具。

候选模型必须留下可观察的调查过程，不能只猜一个补丁就交卷。Scenario completion
gate 会在接受普通 Final 之前，要求显式假设、至少一个已否决假设、相互链接的证据、
Git 考古、PostgreSQL 与 SQLite 取证、离线 Browser 调查、运行时验证，以及内容
充分的 `INVESTIGATION.md`。随后隐藏裁判还会在全新状态、变异用例、Golden
Replay、安全规则和场景私有 Truth Graph 上验证补丁。通过 gate 只说明调查覆盖面
达标，不代表结论正确。

标准 Completion Contract 不再设置凑数式最低调用次数，而是要求 14 个假设
（其中六个必须被否决）、60 条证据、Git / 数据库 / Browser / 运行时 /
跨仓库 / 事故覆盖、分布在分诊、止损、修复、恢复四阶段的 40 组不同
「服务 × 信号 × 窗口」观察、全部八个服务、八张票据的明确结论、至少 140 个
逻辑 Tick、按 Baseline → Canary → Replay → Soak 顺序完成且后三项成功，以及
6,500 字符报告。裁判另行扣除盲改、重复劳动、为幽灵 Bug 改代码、危险动作、
提权或越界探测、修改取证数据库、误信低权威来源和缺少最终验证。

候选沙箱默认只有 0.5 CPU、256 MiB RAM、256 个 PID 和 1.5 GiB 临时工作区。
单样本 Quick Check 可能撒谎；隐藏裁判会重新执行 Static Scope、Regression、
Mutation、Runtime 与全新数据库 Golden Replay。

标准题的难度校准目标是：在 60 分钟硬时限内持续区分强软件工程 Agent。这是校准
目标，不是墙上时间承诺；EvilBench 不会用 `sleep`、随机延迟或强制等待来充数。
难度必须来自不可省略的证据工作、冲突来源、对脚本化故障的有界恢复和隐藏验收。
一旦强 Agent 找到实质捷径，就应升级场景版本并重新校准。

事故中的 180 tick 是确定性逻辑回放步数，不是 180 分钟墙上时间。真实执行默认
现为 30 分钟软告警、60 分钟硬停止。EvilBench 会记录逻辑模型轮次、真实
Provider HTTP 请求数（包含重试）、输入/输出 Token、工具调用和有效运行时间，
并支持可选 Token 上限；但不会把美元成本归一化，因为缓存读写、隐藏推理 Token、
Batch/服务挡位、折扣及兼容 API 的 usage 口径无法在 Provider 之间可靠比较。

每条候选事件都带稳定 Agent 身份。当前内置执行器明确是单 Agent，因此生成一张
单节点 Agent Graph；事件和归档协议已经支持 spawn、delegation、角色、父子关系
及逐 Agent 资源聚合，外部多 Agent 编排器以后无需重定义历史数据格式。平台不会
把「协议已准备」宣传成「内置多 Agent 调度器已经完成」。

对比模型时可以指定同一个未公开实例种子。种子会确定性改变不透明文件路径、运行
单元、Git 历史、离线语料和事故回放；它会进入归档以便复现，但不会复制进候选
工作区。不同模型必须复用相同种子才适合逐项比较。

场景维护者可以运行与 CI 相同的 Oracle、近似错误补丁、脏数据库、二进制取证和
资源限制校验：

```bash
make scenario-validate
```

## 快速开始

环境要求：

- Linux 与 Rootless Docker / Docker Compose；
- GNU Make。

```bash
cp .env.example .env
# 如果本机 uid 不是 1000，请修改 .env 中的 ROOTLESS_DOCKER_SOCKET。
make deploy
```

`make deploy` 会自动检查 Rootless Docker、构建隔离候选沙箱与全部应用镜像、启动
所有服务并打印运行状态。完成后打开 `http://127.0.0.1:5173`。

`RUNNER_CONCURRENCY=2` 会初始化全新数据库；之后可从管理员后台无重启修改。
每个活跃槽位都可能占用配置的单沙箱 CPU、内存和工作区上限，并独立发起
Provider 请求；小型主机或 API 限流较低时应主动调低。HTTP 408/425/429 与常见
5xx 会执行有界、遵循 `Retry-After` 的退避；超过重试预算仍不可用时，运行才会
明确失败。

只要存在排队、准备、运行或评分中的任务，部署与停止命令都会拒绝执行。请先等待
任务结束，或在 WebUI 中取消。如果确实要主动放弃任务，可以使用
`ALLOW_ACTIVE_RUN_DISRUPTION=1 make deploy` 绕过保护；Runner 启动后会把被中断
的任务明确标成失败，因为内存中的模型对话无法安全重建。

Node.js 22+、pnpm、Python 3.12+ 和 uv 只在宿主机参与开发时需要；一键部署会在
容器内构建应用依赖。

全新数据库首次打开时会进入初始管理员创建页面。如果初始化期间服务可能被其他人
访问，请在启动前设置 `SETUP_TOKEN`。公开注册默认关闭，管理员可在后台即时开关，
不需要重启服务。

WebUI 默认使用简体中文，可以从右上角切换到英文。UI 和 API 默认只监听回环地址；
不要把开发环境直接暴露给不可信网络。

## 账户与管理员后台

认证由应用自身实现，不依赖 Caddy 等反向代理：

- 首次管理员初始化与可选公开注册；
- 使用同一个唯一账户名完成登录与界面展示，不依赖邮件服务；
- 密码最低 8 位，使用 scrypt 哈希并限制连续登录失败；
- `admin` / `user` 两种角色；
- HttpOnly 会话 Cookie、写操作 CSRF 防护、会话查看与撤销；
- 按用户隔离模型配置、运行、事件、图谱和报告；
- 管理员创建账户、启停账户、修改角色及撤销全部会话；
- 实时监控 API、Runner、PostgreSQL、队列、CPU、内存、磁盘和 Rootless Docker。

管理员能查看历史与全局 Benchmark 数据；普通用户只能访问映射到自己账户的资源。

## 对外部署

项目不捆绑 Caddy、Nginx、Traefik、DNS 或证书管理。生产 Compose 只暴露一个 Web
入口，并在容器内部代理 `/api/v1`；API、Runner 和 PostgreSQL 保持在内部网络。

```bash
cp .env.production.example .env.production
# 替换全部 CHANGE_ME，并填写真实 WEB_ORIGIN。
make deploy-public
```

用户自行把反向代理指向 `WEB_BIND_PORT`。公网入口使用 HTTPS 时必须保持
`SESSION_COOKIE_SECURE=true`。`make deploy-public` 会拒绝占位密钥、非 HTTPS
入口以及不安全的会话 Cookie。没有设置 `SETUP_TOKEN` 时，不要把尚未初始化的实例
暴露到公网。

## 停止部署

```bash
make down
```

该命令会停止并移除应用容器与 Compose 网络，但保留 PostgreSQL 数据卷。以后再次
执行 `make deploy`，现有账户、设置和 Benchmark 数据仍会保留。存在排队或活跃
任务时该命令会拒绝执行；只有明确准备放弃这些任务时，才使用
`ALLOW_ACTIVE_RUN_DISRUPTION=1 make down`。

## 仓库结构

```text
apps/web/                  React/TypeScript 控制台
apps/api/                  FastAPI API、Worker、Runner 与评分器
suites/                    版本化题族/数据划分 Manifest 与就绪策略
scenarios/                 版本化 Scenario SDK 包、隐藏真相与合成语料
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
- [`CHANGELOG.md`](CHANGELOG.md) — 平台版本迭代记录。

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
