import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Blocks,
  Bot,
  Box,
  Braces,
  CheckCircle2,
  ChevronRight,
  CircleDot,
  Clock3,
  Database,
  Download,
  ExternalLink,
  FileCode2,
  Fingerprint,
  FlaskConical,
  Gauge,
  GitBranch,
  GitCommitHorizontal,
  Home,
  KeyRound,
  Languages,
  Lightbulb,
  ListFilter,
  Menu,
  Network,
  OctagonAlert,
  Play,
  Plus,
  Radar,
  ScrollText,
  Settings,
  ShieldAlert,
  ShieldCheck,
  Skull,
  SquareTerminal,
  TimerReset,
  Trash2,
  X,
  XCircle,
  Zap,
} from "lucide-react";
import {
  type FormEvent,
  lazy,
  type ReactNode,
  Suspense,
  useState,
} from "react";
import {
  Link,
  NavLink,
  Navigate,
  Route,
  Routes,
  useNavigate,
  useParams,
} from "react-router-dom";
import { api } from "./lib/api";
import { useLocale } from "./lib/i18n";
import type {
  ModelProvider,
  Run,
  RunEvent,
  RunStatus,
  Task,
} from "./lib/types";

const InvestigationGraphView = lazy(
  () => import("./components/InvestigationGraph"),
);
const ScoreRadar = lazy(() => import("./components/ScoreRadar"));

export default function App() {
  const [mobileNav, setMobileNav] = useState(false);
  const { isChinese, text, toggle } = useLocale();
  return (
    <div className="app-shell">
      <aside className={`sidebar ${mobileNav ? "sidebar--open" : ""}`}>
        <div className="brand">
          <div className="brand__mark">
            <Skull size={22} strokeWidth={1.8} />
          </div>
          <div>
            <strong>The Evil Repository</strong>
            <span>{text("EvilBench 控制台", "EvilBench Control Plane")}</span>
          </div>
        </div>
        <nav className="nav">
          <NavItem
            to="/"
            icon={<Home size={17} />}
            label={text("总览", "Overview")}
            end
          />
          <NavItem
            to="/scenarios"
            icon={<Blocks size={17} />}
            label={text("场景", "Scenarios")}
          />
          <NavItem
            to="/models"
            icon={<Bot size={17} />}
            label={text("模型配置", "Model profiles")}
          />
          <NavItem
            to="/runs"
            icon={<Activity size={17} />}
            label={text("运行记录", "Runs")}
          />
          <NavItem
            to="/settings"
            icon={<Settings size={17} />}
            label={text("设置", "Settings")}
          />
        </nav>
        <div className="sidebar__footer">
          <span className="status-dot status-dot--safe" />
          <div>
            <strong>{text("Rootless 隔离边界", "Rootless boundary")}</strong>
            <small>{text("本机控制平面", "Local control plane")}</small>
          </div>
        </div>
      </aside>
      {mobileNav && (
        <button className="nav-scrim" onClick={() => setMobileNav(false)} />
      )}
      <main className="main">
        <header className="topbar">
          <button
            className="icon-button topbar__menu"
            onClick={() => setMobileNav(true)}
          >
            <Menu size={19} />
          </button>
          <div className="topbar__context">
            <span className="eyebrow">AI AGENT CTF / INCIDENT RESPONSE</span>
            <span className="topbar__divider" />
            <span>localhost</span>
          </div>
          <div className="topbar__actions">
            <button
              className="quiet-link language-toggle"
              type="button"
              onClick={toggle}
              title={text("切换到英文", "Switch to Chinese")}
            >
              <Languages size={13} />
              {isChinese ? "EN" : "中文"}
            </button>
            <a
              className="quiet-link"
              href="https://www.gnu.org/licenses/agpl-3.0.html"
              target="_blank"
              rel="noreferrer"
            >
              AGPLv3 <ExternalLink size={12} />
            </a>
            <Link className="button button--small" to="/runs/new">
              <Play size={14} fill="currentColor" />{" "}
              {text("新建运行", "New run")}
            </Link>
          </div>
        </header>
        <div className="page-wrap">
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/scenarios" element={<ScenariosPage />} />
            <Route path="/models" element={<ModelsPage />} />
            <Route path="/runs" element={<RunsPage />} />
            <Route path="/runs/new" element={<NewRunPage />} />
            <Route path="/runs/:runId" element={<RunDetailPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </div>
      </main>
    </div>
  );
}

function NavItem({
  to,
  icon,
  label,
  end,
}: {
  to: string;
  icon: ReactNode;
  label: string;
  end?: boolean;
}) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) => (isActive ? "active" : "")}
    >
      {icon}
      <span>{label}</span>
      <ChevronRight className="nav__chevron" size={14} />
    </NavLink>
  );
}

function DashboardPage() {
  const { isChinese, text } = useLocale();
  const summary = useQuery({
    queryKey: ["summary"],
    queryFn: api.summary,
    refetchInterval: 5_000,
  });
  const runs = useQuery({
    queryKey: ["runs"],
    queryFn: api.runs,
    refetchInterval: 5_000,
  });
  const tasks = useQuery({ queryKey: ["tasks"], queryFn: api.tasks });
  const data = summary.data;
  return (
    <>
      <PageHeader
        eyebrow={text("控制中心", "CONTROL ROOM")}
        title={text("高压之下，证据为王。", "Evidence under pressure.")}
        description={text(
          "观察模型如何调查恶意仓库、脏数据与被污染的权威信息，同时始终待在沙箱边界内。",
          "Watch models investigate hostile repositories, dirty data, and poisoned authority without crossing the sandbox boundary.",
        )}
        action={
          <Link className="button" to="/runs/new">
            <Play size={15} fill="currentColor" />{" "}
            {text("发起调查", "Launch investigation")}
          </Link>
        }
      />
      <div className="stat-grid">
        <StatCard
          icon={<FlaskConical />}
          label={text("场景", "Scenarios")}
          value={data?.tasks ?? "—"}
          detail={text("版本化 SDK 包", "Versioned SDK packages")}
        />
        <StatCard
          icon={<Bot />}
          label={text("候选模型", "Candidate models")}
          value={data?.models ?? "—"}
          detail={text("Provider 配置", "Provider profiles")}
        />
        <StatCard
          icon={<Activity />}
          label={text("活跃运行", "Active runs")}
          value={data?.active_runs ?? "—"}
          detail={text(
            `共 ${data?.total_runs ?? 0} 次调查`,
            `${data?.total_runs ?? 0} total investigations`,
          )}
          accent={Boolean(data?.active_runs)}
        />
        <StatCard
          icon={<Radar />}
          label={text("平均得分", "Average score")}
          value={
            data?.average_score == null ? "—" : Math.round(data.average_score)
          }
          detail={text("满分 1,200", "out of 1,200")}
        />
      </div>
      <div className="dashboard-grid">
        <section className="panel panel--wide">
          <PanelHeading
            icon={<Activity size={16} />}
            title={text("最近调查", "Recent investigations")}
            detail={text(
              "Runner 队列实时状态",
              "Live state from the Runner queue",
            )}
            action={<Link to="/runs">{text("查看全部", "View all")}</Link>}
          />
          <RunTable runs={runs.data ?? []} compact />
        </section>
        <section className="panel">
          <PanelHeading
            icon={<ShieldCheck size={16} />}
            title={text("边界状态", "Boundary posture")}
            detail={text(
              "当前控制平面就绪情况",
              "Current control-plane readiness",
            )}
          />
          <div className="boundary-list">
            <BoundaryRow
              label="Rootless Docker"
              good={Boolean(data?.docker_ready)}
            />
            <BoundaryRow
              label={text("Runner 工作进程", "Runner worker")}
              good={Boolean(data?.runner_enabled)}
            />
            <BoundaryRow
              label={text("候选环境网络", "Candidate network")}
              good
              value="none"
            />
            <BoundaryRow
              label={text("宿主机绑定挂载", "Host bind mounts")}
              good
              value={text("拒绝", "denied")}
            />
            <BoundaryRow
              label={text("Provider 密钥", "Provider secrets")}
              good
              value={text("仅限控制平面", "control plane only")}
            />
          </div>
        </section>
        <section className="panel panel--wide scenario-spotlight">
          <div className="scenario-spotlight__badge">
            <Skull size={28} />
          </div>
          <div className="scenario-spotlight__copy">
            <span className="eyebrow">
              {text("标准场景", "CANONICAL SCENARIO")}
            </span>
            <h2>
              {tasks.data?.[0]
                ? taskCopy(tasks.data[0], isChinese).name
                : text("终焉仓库", "The Terminal Repository")}
            </h2>
            <p>
              {text(
                "两段 Git 历史，一个损坏的 CI 预言机，两套脏数据库，一片充斥权威注入的离线互联网，以及一个极小的正确补丁。",
                "Two Git histories. A broken CI oracle. Two dirty databases. A synthetic internet full of authority injection. One tiny correct patch.",
              )}
            </p>
          </div>
          <div className="pressure-grid">
            <Pressure value="5K" label={text("文件", "files")} />
            <Pressure value="2K" label={text("提交", "commits")} />
            <Pressure value="100MB" label={text("离线文档", "offline docs")} />
            <Pressure value="180m" label={text("硬限制", "hard limit")} />
          </div>
          <Link className="button button--ghost" to="/scenarios">
            {text("查看场景", "Inspect scenario")} <ArrowRight size={15} />
          </Link>
        </section>
      </div>
    </>
  );
}

function ScenariosPage() {
  const { text } = useLocale();
  const tasks = useQuery({ queryKey: ["tasks"], queryFn: api.tasks });
  return (
    <>
      <PageHeader
        eyebrow="SCENARIO SDK"
        title={text("版本化的敌意世界。", "Hostile worlds, versioned.")}
        description={text(
          "每个场景独立封装仓库、数据库、注入内容、故障脚本、隐藏裁判、回放契约与离线互联网。",
          "Each scenario owns its repositories, databases, injections, failure scripts, hidden judge, replay contract, and offline internet.",
        )}
      />
      <div className="card-stack">
        {(tasks.data ?? []).map((task) => (
          <ScenarioCard key={task.id} task={task} />
        ))}
        {!tasks.isLoading && !tasks.data?.length && (
          <EmptyState
            title={text("尚未加载场景", "No scenarios loaded")}
            detail={text(
              "请添加有效的 Scenario SDK 目录。",
              "Add a valid Scenario SDK directory.",
            )}
          />
        )}
      </div>
    </>
  );
}

function ScenarioCard({ task }: { task: Task }) {
  const { isChinese, text } = useLocale();
  const pressure = task.manifest.context_pressure;
  const scoring = task.manifest.scoring ?? {};
  const localized = taskCopy(task, isChinese);
  return (
    <article className="scenario-card">
      <div className="scenario-card__icon">
        <Skull size={30} />
      </div>
      <div className="scenario-card__main">
        <div className="scenario-card__title">
          <div>
            <span className="eyebrow">SCENARIO / {task.version}</span>
            <h2>{localized.name}</h2>
          </div>
          <span className="pill pill--lime">{text("已启用", "enabled")}</span>
        </div>
        <p>{localized.description}</p>
        <div className="tag-row">
          <span>
            <GitBranch size={13} /> {text("跨仓库", "cross-repository")}
          </span>
          <span>
            <Database size={13} /> {text("脏数据库", "dirty database")}
          </span>
          <span>
            <ShieldAlert size={13} /> Prompt Injection
          </span>
          <span>
            <Network size={13} /> {text("离线互联网", "offline internet")}
          </span>
          <span>
            <TimerReset size={13} /> {text("脚本化故障", "scripted faults")}
          </span>
        </div>
        <div className="scenario-metrics">
          <Metric
            label={text("文件", "Files")}
            value={formatCompact(pressure?.target_files)}
          />
          <Metric
            label={text("Git 提交", "Git commits")}
            value={formatCompact(pressure?.target_git_commits)}
          />
          <Metric
            label={text("镜像内容", "Mirror")}
            value={formatBytes(pressure?.target_mirror_bytes)}
          />
          <Metric
            label={text("最高分", "Maximum score")}
            value={
              Object.values(scoring).reduce((sum, value) => sum + value, 0) ||
              1_200
            }
          />
        </div>
      </div>
      <div className="scenario-card__actions">
        <a
          className="button button--ghost"
          href={`http://127.0.0.1:8080/api/v1/tasks/${task.id}/export`}
        >
          <Download size={14} /> {text("元数据", "Metadata")}
        </a>
        <Link className="button" to={`/runs/new?task=${task.id}`}>
          <Play size={14} fill="currentColor" /> {text("运行", "Run")}
        </Link>
      </div>
    </article>
  );
}

function ModelsPage() {
  const { text } = useLocale();
  const queryClient = useQueryClient();
  const models = useQuery({ queryKey: ["models"], queryFn: api.models });
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");
  const [provider, setProvider] = useState<ModelProvider>("openai_responses");
  const [baseUrl, setBaseUrl] = useState(
    providerDefaultUrl("openai_responses"),
  );
  const create = useMutation({
    mutationFn: api.createModel,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["models"] });
      setOpen(false);
      setError("");
    },
    onError: (cause) => setError(String(cause)),
  });
  const remove = useMutation({
    mutationFn: api.deleteModel,
    onSuccess: () =>
      void queryClient.invalidateQueries({ queryKey: ["models"] }),
  });
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    create.mutate({
      name: data.get("name"),
      provider,
      base_url: data.get("base_url"),
      model_id: data.get("model_id"),
      api_key: data.get("api_key") || null,
      native_tools: data.get("native_tools") === "on",
      parameters:
        provider === "anthropic"
          ? { temperature: 0, max_tokens: 8192 }
          : provider === "openai_responses"
            ? {}
            : { temperature: 0 },
      enabled: true,
    });
  };
  return (
    <>
      <PageHeader
        eyebrow={text("模型注册表", "MODEL REGISTRY")}
        title={text("候选模型与裁判模型。", "Candidates and judges.")}
        description={text(
          "Provider 凭据只在控制平面加密保存，绝不会进入候选沙箱或运行归档。",
          "Provider credentials are encrypted in the control plane and never enter a candidate sandbox or run archive.",
        )}
        action={
          <button className="button" onClick={() => setOpen(true)}>
            <Plus size={15} /> {text("添加配置", "Add profile")}
          </button>
        }
      />
      <div className="model-grid">
        {(models.data ?? []).map((model) => (
          <article className="model-card" key={model.id}>
            <div className="model-card__head">
              <div className="model-mark">
                <Bot size={20} />
              </div>
              <div>
                <h3>{model.name}</h3>
                <span>{providerLabel(model.provider)}</span>
              </div>
              <button
                className="icon-button icon-button--danger"
                onClick={() => remove.mutate(model.id)}
                title={text("删除模型配置", "Delete model profile")}
              >
                <Trash2 size={15} />
              </button>
            </div>
            <dl>
              <div>
                <dt>{text("模型", "Model")}</dt>
                <dd>{model.model_id}</dd>
              </div>
              <div>
                <dt>{text("端点", "Endpoint")}</dt>
                <dd>{model.base_url}</dd>
              </div>
              <div>
                <dt>{text("工具协议", "Tool protocol")}</dt>
                <dd>
                  {model.native_tools
                    ? text("原生函数调用", "Native function calls")
                    : text("JSON 回退协议", "JSON fallback")}
                </dd>
              </div>
              <div>
                <dt>{text("凭据", "Credential")}</dt>
                <dd className={model.has_api_key ? "text-safe" : ""}>
                  {model.has_api_key
                    ? text("已加密", "Encrypted")
                    : text("无需提供", "Not required")}
                </dd>
              </div>
            </dl>
          </article>
        ))}
        {!models.isLoading && !models.data?.length && (
          <button
            className="model-card model-card--empty"
            onClick={() => setOpen(true)}
          >
            <Plus size={28} />
            <strong>{text("添加第一个模型", "Add your first model")}</strong>
            <span>OpenAI Responses · Anthropic · Compatible · Ollama</span>
          </button>
        )}
      </div>
      {open && (
        <Modal
          title={text("添加模型配置", "Add model profile")}
          onClose={() => setOpen(false)}
        >
          <form className="form" onSubmit={submit}>
            <Field label={text("配置名称", "Profile name")}>
              <input name="name" required placeholder="Claude Sonnet" />
            </Field>
            <Field
              label="Provider"
              hint={text(
                "选择实际 API 协议，而不是只按模型品牌选择。",
                "Choose the actual API protocol, not only the model brand.",
              )}
            >
              <select
                name="provider"
                value={provider}
                onChange={(event) => {
                  const next = event.target.value as ModelProvider;
                  setProvider(next);
                  setBaseUrl(providerDefaultUrl(next));
                }}
              >
                <option value="openai_responses">OpenAI Responses API</option>
                <option value="anthropic">Anthropic Messages API</option>
                <option value="openai_compatible">OpenAI-compatible API</option>
                <option value="ollama">Ollama</option>
              </select>
            </Field>
            <Field label={text("基础 URL", "Base URL")}>
              <input
                name="base_url"
                type="url"
                required
                value={baseUrl}
                onChange={(event) => setBaseUrl(event.target.value)}
              />
            </Field>
            <Field label={text("模型 ID", "Model ID")}>
              <input name="model_id" required placeholder="model-name" />
            </Field>
            <Field
              label="API key"
              hint={text(
                "静态加密保存；使用 Ollama 时可留空。",
                "Encrypted at rest; leave blank for Ollama.",
              )}
            >
              <input
                name="api_key"
                type="password"
                autoComplete="new-password"
              />
            </Field>
            <label className="check-row">
              <input name="native_tools" type="checkbox" defaultChecked />
              <span>
                <strong>
                  {text("原生函数调用", "Native function calling")}
                </strong>
                <small>
                  {text(
                    "关闭后使用 EvilBench 的严格 JSON 回退协议。",
                    "Disable to use EvilBench's strict JSON fallback protocol.",
                  )}
                </small>
              </span>
            </label>
            {error && <div className="inline-error">{error}</div>}
            <div className="modal__actions">
              <button
                className="button button--ghost"
                type="button"
                onClick={() => setOpen(false)}
              >
                {text("取消", "Cancel")}
              </button>
              <button className="button" disabled={create.isPending}>
                <KeyRound size={14} />{" "}
                {text("保存加密配置", "Save encrypted profile")}
              </button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}

function RunsPage() {
  const { text } = useLocale();
  const runs = useQuery({
    queryKey: ["runs"],
    queryFn: api.runs,
    refetchInterval: 4_000,
  });
  return (
    <>
      <PageHeader
        eyebrow={text("运行归档", "RUN ARCHIVE")}
        title={text("每次调查，都可回放。", "Every investigation, replayable.")}
        description={text(
          "比较最终结果、图谱质量、安全状态、资源使用与假设演化。",
          "Compare outcomes, graph quality, security posture, resource use, and hypothesis evolution.",
        )}
        action={
          <Link className="button" to="/runs/new">
            <Play size={15} fill="currentColor" /> {text("新建运行", "New run")}
          </Link>
        }
      />
      <section className="panel">
        <div className="toolbar">
          <span>
            <ListFilter size={14} />{" "}
            {text("最近 200 次运行", "Latest 200 runs")}
          </span>
          <span className="toolbar__count">
            {text(
              `${runs.data?.length ?? 0} 条记录`,
              `${runs.data?.length ?? 0} records`,
            )}
          </span>
        </div>
        <RunTable runs={runs.data ?? []} />
      </section>
    </>
  );
}

function NewRunPage() {
  const { isChinese, text } = useLocale();
  const navigate = useNavigate();
  const tasks = useQuery({ queryKey: ["tasks"], queryFn: api.tasks });
  const models = useQuery({ queryKey: ["models"], queryFn: api.models });
  const [error, setError] = useState("");
  const create = useMutation({
    mutationFn: api.createRun,
    onSuccess: (run) => navigate(`/runs/${run.id}`),
    onError: (cause) => setError(String(cause)),
  });
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    create.mutate({
      task_id: data.get("task_id"),
      candidate_model_id: data.get("candidate_model_id"),
      judge_model_id: data.get("judge_model_id") || null,
      repetitions: 1,
      temperature: 0,
      soft_seconds: Number(data.get("soft_seconds")),
      hard_seconds: Number(data.get("hard_seconds")),
      soft_tool_calls: Number(data.get("soft_tool_calls")),
      hard_tool_calls: Number(data.get("hard_tool_calls")),
    });
  };
  return (
    <>
      <PageHeader
        eyebrow={text("新调查", "NEW INVESTIGATION")}
        title={text("把一个模型扔进地狱。", "Drop a model into hell.")}
        description={text(
          "系统会按所选场景生成全新的 Rootless Docker 工作区，并在评分完成后销毁。",
          "A fresh Rootless Docker workspace will be generated from the selected Scenario and destroyed after grading.",
        )}
      />
      <form className="run-builder" onSubmit={submit}>
        <section className="panel">
          <PanelHeading
            icon={<Blocks size={16} />}
            title={text("场景", "Scenario")}
            detail={text("版本化世界包", "Versioned world package")}
          />
          <div className="choice-grid">
            {(tasks.data ?? []).map((task, index) => (
              <label className="choice-card" key={task.id}>
                <input
                  type="radio"
                  name="task_id"
                  value={task.id}
                  defaultChecked={index === 0}
                />
                <div className="choice-card__check">
                  <CheckCircle2 size={16} />
                </div>
                <Skull size={24} />
                <strong>{taskCopy(task, isChinese).name}</strong>
                <span>{taskCopy(task, isChinese).description}</span>
              </label>
            ))}
          </div>
        </section>
        <section className="panel">
          <PanelHeading
            icon={<Bot size={16} />}
            title={text("模型", "Models")}
            detail={text("候选模型与可选裁判", "Candidate and optional judge")}
          />
          <div className="form-grid">
            <Field label={text("候选模型", "Candidate")}>
              <select name="candidate_model_id" required defaultValue="">
                <option value="" disabled>
                  {text("选择候选模型", "Select a candidate")}
                </option>
                {(models.data ?? []).map((model) => (
                  <option value={model.id} key={model.id}>
                    {model.name} · {model.model_id}
                  </option>
                ))}
              </select>
            </Field>
            <Field
              label={text("独立裁判", "Independent judge")}
              hint={text(
                "终焉仓库场景中可选。",
                "Optional for the terminal scenario.",
              )}
            >
              <select name="judge_model_id" defaultValue="">
                <option value="">
                  {text("仅使用确定性裁判", "Deterministic judge only")}
                </option>
                {(models.data ?? []).map((model) => (
                  <option value={model.id} key={model.id}>
                    {model.name}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          {!models.data?.length && (
            <div className="callout callout--warning">
              <AlertTriangle size={17} />
              <span>
                {text(
                  "发起运行前请先添加模型配置。",
                  "Add a model profile before launching a run.",
                )}
              </span>
              <Link to="/models">
                {text("打开模型注册表", "Open model registry")}
              </Link>
            </div>
          )}
        </section>
        <section className="panel">
          <PanelHeading
            icon={<Gauge size={16} />}
            title={text("预算", "Budgets")}
            detail={text(
              "软性扣分曲线与硬停止",
              "Soft score curve and hard stop",
            )}
          />
          <div className="budget-grid">
            <Field label={text("软时间限制（秒）", "Soft time (seconds)")}>
              <input
                name="soft_seconds"
                type="number"
                defaultValue={5400}
                min={60}
              />
            </Field>
            <Field label={text("硬时间限制（秒）", "Hard time (seconds)")}>
              <input
                name="hard_seconds"
                type="number"
                defaultValue={10800}
                min={300}
              />
            </Field>
            <Field label={text("软工具调用限制", "Soft tool calls")}>
              <input
                name="soft_tool_calls"
                type="number"
                defaultValue={500}
                min={10}
              />
            </Field>
            <Field label={text("硬工具调用限制", "Hard tool calls")}>
              <input
                name="hard_tool_calls"
                type="number"
                defaultValue={1000}
                min={20}
              />
            </Field>
          </div>
        </section>
        <section className="launch-strip">
          <div>
            <ShieldCheck size={20} />
            <span>
              <strong>
                {text("全新隔离环境", "Fresh isolated environment")}
              </strong>
              {text(
                "Rootless · 无网络 · 无宿主机挂载 · 移除全部 capabilities",
                "Rootless · network none · no host mounts · capabilities dropped",
              )}
            </span>
          </div>
          {error && <span className="text-danger">{error}</span>}
          <button
            className="button button--large"
            disabled={!models.data?.length || create.isPending}
          >
            <Zap size={16} fill="currentColor" />{" "}
            {text("创建运行", "Create run")}
          </button>
        </section>
      </form>
    </>
  );
}

function RunDetailPage() {
  const { locale, text } = useLocale();
  const { runId = "" } = useParams();
  const [tab, setTab] = useState<"overview" | "graph" | "audit" | "score">(
    "overview",
  );
  const run = useQuery({
    queryKey: ["run", runId],
    queryFn: () => api.run(runId),
    refetchInterval: (query) =>
      isTerminal(query.state.data?.status) ? false : 2_000,
  });
  const events = useQuery({
    queryKey: ["events", runId],
    queryFn: () => api.events(runId),
    refetchInterval: isTerminal(run.data?.status) ? false : 2_000,
  });
  const graph = useQuery({
    queryKey: ["graph", runId],
    queryFn: () => api.graph(runId),
    refetchInterval: isTerminal(run.data?.status) ? false : 3_000,
  });
  const data = run.data;
  if (run.isLoading) return <LoadingState />;
  if (!data) {
    return (
      <EmptyState
        title={text("找不到运行", "Run not found")}
        detail={text(
          "归档中不存在这次运行。",
          "The archive does not contain this run.",
        )}
      />
    );
  }
  const dimensions = data.scorecard.dimensions ?? {};
  return (
    <>
      <div className="run-hero">
        <div>
          <div className="run-hero__meta">
            <StatusPill status={data.status} />
            <span>{shortId(data.id)}</span>
            <span>{new Date(data.created_at).toLocaleString(locale)}</span>
          </div>
          <h1>{stageLabel(data.stage, locale)}</h1>
          <p>
            {data.status === "completed"
              ? text(
                  "隐藏裁判流水线已经归档本次调查。",
                  "The hidden judge pipeline has archived this investigation.",
                )
              : text(
                  "Runner 正在从隔离候选环境中流式传输可观察的调查状态。",
                  "The Runner is streaming observable investigation state from the isolated candidate.",
                )}
          </p>
        </div>
        <div className="run-score">
          <span>{text("得分", "Score")}</span>
          <strong>{data.score == null ? "—" : Math.round(data.score)}</strong>
          <small>/ {data.scorecard.maximum ?? 1_200}</small>
        </div>
      </div>
      <div className="run-kpis">
        <MiniKpi
          icon={<SquareTerminal />}
          label={text("工具调用", "Tool calls")}
          value={data.tool_calls}
        />
        <MiniKpi
          icon={<Braces />}
          label={text("输入 Token", "Input tokens")}
          value={formatCompact(data.input_tokens)}
        />
        <MiniKpi
          icon={<Bot />}
          label={text("输出 Token", "Output tokens")}
          value={formatCompact(data.output_tokens)}
        />
        <MiniKpi
          icon={<Clock3 />}
          label={text("耗时", "Elapsed")}
          value={duration(data.started_at, data.completed_at, locale)}
        />
        <MiniKpi
          icon={<Lightbulb />}
          label={text("假设", "Hypotheses")}
          value={graph.data?.hypotheses.length ?? 0}
        />
        <MiniKpi
          icon={<Fingerprint />}
          label={text("证据", "Evidence")}
          value={graph.data?.evidence.length ?? 0}
        />
      </div>
      <div className="tabs">
        <button
          className={tab === "overview" ? "active" : ""}
          onClick={() => setTab("overview")}
        >
          <Activity size={14} /> {text("总览", "Overview")}
        </button>
        <button
          className={tab === "graph" ? "active" : ""}
          onClick={() => setTab("graph")}
        >
          <Network size={14} /> {text("假设图谱", "Hypothesis graph")}
        </button>
        <button
          className={tab === "audit" ? "active" : ""}
          onClick={() => setTab("audit")}
        >
          <ScrollText size={14} /> {text("审计", "Audit")}
        </button>
        <button
          className={tab === "score" ? "active" : ""}
          onClick={() => setTab("score")}
        >
          <Radar size={14} /> {text("裁判", "Judge")}
        </button>
      </div>
      {tab === "overview" && (
        <RunOverview run={data} events={events.data ?? []} />
      )}
      {tab === "graph" && (
        <section className="panel panel--flush">
          <div className="graph-header">
            <div>
              <span className="eyebrow">
                {text("可观察调查账本", "OBSERVABLE INVESTIGATION LEDGER")}
              </span>
              <h2>
                {text("假设图谱 / 真相树", "Hypothesis Graph / Truth Tree")}
              </h2>
            </div>
            <div className="graph-legend">
              <span>
                <i className="legend-dot legend-dot--evidence" />{" "}
                {text("证据", "Evidence")}
              </span>
              <span>
                <i className="legend-dot legend-dot--hypothesis" />{" "}
                {text("假设", "Hypothesis")}
              </span>
              <span>
                <i className="legend-line legend-line--conflict" />{" "}
                {text("矛盾", "Contradicts")}
              </span>
            </div>
          </div>
          <Suspense fallback={<LoadingState />}>
            <InvestigationGraphView
              graph={
                graph.data ?? {
                  hypotheses: [],
                  revisions: [],
                  evidence: [],
                  edges: [],
                }
              }
            />
          </Suspense>
        </section>
      )}
      {tab === "audit" && <AuditTimeline events={events.data ?? []} />}
      {tab === "score" && (
        <div className="judge-grid">
          <section className="panel">
            <PanelHeading
              icon={<Radar size={16} />}
              title={text("1,200 分画像", "1,200-point profile")}
              detail={text("隐藏裁判维度", "Hidden judge dimensions")}
            />
            {Object.keys(dimensions).length ? (
              <Suspense fallback={<LoadingState />}>
                <ScoreRadar dimensions={dimensions} />
              </Suspense>
            ) : (
              <EmptyState
                title={text("等待裁判", "Waiting for the judge")}
                detail={text(
                  "归档完成后显示得分。",
                  "Scores appear after archive.",
                )}
              />
            )}
          </section>
          <section className="panel score-list">
            <PanelHeading
              icon={<Gauge size={16} />}
              title={text("评分维度账本", "Dimension ledger")}
              detail={text("分数与硬上限", "Points and hard caps")}
            />
            {Object.entries(dimensions)
              .sort(([, a], [, b]) => b.maximum - a.maximum)
              .map(([key, metric]) => (
                <div className="score-row" key={key}>
                  <div>
                    <strong>{metric.label || label(key, locale)}</strong>
                    <span>
                      {metric.score} / {metric.maximum}
                    </span>
                  </div>
                  <div className="score-bar">
                    <i
                      style={{
                        width: `${(metric.score / metric.maximum) * 100}%`,
                      }}
                    />
                  </div>
                </div>
              ))}
            {data.scorecard.caps?.map((cap) => (
              <div className="callout callout--danger" key={cap.reason}>
                <OctagonAlert size={16} />
                <span>{cap.reason}</span>
                <strong>{text(`上限 ${cap.max}`, `cap ${cap.max}`)}</strong>
              </div>
            ))}
          </section>
        </div>
      )}
      <div className="run-footer-actions">
        <a className="button button--ghost" href={api.reportUrl(data.id)}>
          <Download size={14} /> {text("导出报告", "Export report")}
        </a>
        {!isTerminal(data.status) && (
          <button
            className="button button--danger"
            onClick={() => void api.cancelRun(data.id)}
          >
            <X size={14} /> {text("取消运行", "Cancel run")}
          </button>
        )}
      </div>
    </>
  );
}

function RunOverview({ run, events }: { run: Run; events: RunEvent[] }) {
  const { text } = useLocale();
  const latest = events.slice(-8).reverse();
  const violations = events.filter(
    (event) => event.kind === "tool.result" && event.payload.policy_violation,
  );
  const faults = events.filter(
    (event) => event.kind === "tool.result" && event.payload.injected_fault,
  );
  return (
    <div className="run-overview-grid">
      <section className="panel">
        <PanelHeading
          icon={<Activity size={16} />}
          title={text("最新活动", "Latest activity")}
          detail={text("最新事件优先", "Newest event first")}
        />
        <div className="event-list">
          {latest.map((event) => (
            <EventRow event={event} key={event.id} />
          ))}
          {!latest.length && (
            <EmptyState
              title={text("尚无事件", "No events yet")}
              detail={text(
                "Runner 正在准备场景。",
                "The Runner is preparing the Scenario.",
              )}
            />
          )}
        </div>
      </section>
      <div className="side-stack">
        <section className="panel">
          <PanelHeading
            icon={<ShieldAlert size={16} />}
            title={text("对抗性遥测", "Adversarial telemetry")}
          />
          <div className="telemetry-grid">
            <Telemetry
              icon={violations.length ? <XCircle /> : <ShieldCheck />}
              value={violations.length}
              label={text("次边界违规", "boundary violations")}
              danger={Boolean(violations.length)}
            />
            <Telemetry
              icon={<TimerReset />}
              value={faults.length}
              label={text("次脚本化故障", "scripted faults encountered")}
            />
          </div>
        </section>
        <section className="panel">
          <PanelHeading
            icon={<Box size={16} />}
            title={text("隔离包络", "Isolation envelope")}
          />
          <div className="tag-column">
            <span>
              <ShieldCheck size={13} /> Rootless daemon
            </span>
            <span>
              <Network size={13} /> network_mode: none
            </span>
            <span>
              <Database size={13} />{" "}
              {text(
                "通过 Unix socket 访问 PostgreSQL",
                "PostgreSQL via Unix socket",
              )}
            </span>
            <span>
              <FileCode2 size={13} />{" "}
              {text("临时工作区", "ephemeral workspace")}
            </span>
            <span>
              <KeyRound size={13} />{" "}
              {text("无 Provider 密钥", "no provider secrets")}
            </span>
          </div>
        </section>
        {run.error && (
          <section className="panel panel--danger">
            <PanelHeading
              icon={<OctagonAlert size={16} />}
              title={text("Runner 错误", "Runner error")}
            />
            <pre>{run.error}</pre>
          </section>
        )}
      </div>
    </div>
  );
}

function AuditTimeline({ events }: { events: RunEvent[] }) {
  const { locale, text } = useLocale();
  return (
    <section className="panel">
      <PanelHeading
        icon={<ScrollText size={16} />}
        title={text("不可变事件流", "Immutable event stream")}
        detail={text(`${events.length} 个事件`, `${events.length} events`)}
      />
      <div className="audit-list">
        {events.map((event) => (
          <details key={event.id} className="audit-event">
            <summary>
              <span
                className={`event-icon event-icon--${eventKind(event.kind)}`}
              >
                {eventIcon(event.kind)}
              </span>
              <span>
                <strong>{event.kind}</strong>
                <small>
                  #{event.sequence} ·{" "}
                  {new Date(event.created_at).toLocaleTimeString(locale)}
                </small>
              </span>
              <code>
                {event.payload.name ? String(event.payload.name) : ""}
              </code>
            </summary>
            <pre>{JSON.stringify(event.payload, null, 2)}</pre>
          </details>
        ))}
      </div>
    </section>
  );
}

function SettingsPage() {
  const { text } = useLocale();
  return (
    <>
      <PageHeader
        eyebrow={text("本机控制平面", "LOCAL CONTROL PLANE")}
        title={text("安全来自配置。", "Security is configuration.")}
        description={text(
          "界面只展示不涉及秘密的安全状态，运行时密钥始终留在服务端。",
          "The UI intentionally exposes only non-secret posture. Runtime secrets remain server-side.",
        )}
      />
      <div className="settings-grid">
        <section className="panel">
          <PanelHeading
            icon={<ShieldCheck size={16} />}
            title={text("必需的沙箱配置", "Required sandbox profile")}
          />
          <div className="config-code">
            <code>{text("Docker 上下文", "Docker context")}</code>
            <strong>rootless</strong>
            <code>{text("网络", "Network")}</code>
            <strong>none</strong>
            <code>{text("根文件系统", "Root filesystem")}</code>
            <strong>read-only</strong>
            <code>Linux capabilities</code>
            <strong>ALL dropped</strong>
            <code>{text("权限提升", "Privilege escalation")}</code>
            <strong>disabled</strong>
            <code>{text("宿主机挂载", "Host mounts")}</code>
            <strong>none</strong>
          </div>
        </section>
        <section className="panel">
          <PanelHeading
            icon={<GitCommitHorizontal size={16} />}
            title={text("开放设计", "Open design")}
          />
          <p className="panel-copy">
            {text(
              "Scenario SDK 契约、威胁假设、评分和界面行为记录在 ",
              "Scenario SDK contracts, threat assumptions, scoring, and UI behavior are maintained in ",
            )}
            <code>{text("DESIGN.zh-CN.md", "DESIGN.md")}</code>
            {text("，采用 AGPL-3.0-only。", " under AGPL-3.0-only.")}
          </p>
          <a
            className="button button--ghost"
            href="https://github.com/"
            target="_blank"
            rel="noreferrer"
          >
            {text("仓库尚未发布", "Repository not published yet")}{" "}
            <ExternalLink size={14} />
          </a>
        </section>
      </div>
    </>
  );
}

function RunTable({
  runs,
  compact = false,
}: {
  runs: Run[];
  compact?: boolean;
}) {
  const { locale, text } = useLocale();
  if (!runs.length) {
    return (
      <EmptyState
        title={text("尚无调查", "No investigations yet")}
        detail={text(
          "创建一次运行来填充归档。",
          "Create a run to populate the archive.",
        )}
      />
    );
  }
  return (
    <div className="table-scroll">
      <table className="data-table">
        <thead>
          <tr>
            <th>{text("运行", "Run")}</th>
            <th>{text("状态", "Status")}</th>
            <th>{text("阶段", "Stage")}</th>
            <th>{text("工具", "Tools")}</th>
            <th>{text("得分", "Score")}</th>
            {!compact && <th>{text("创建时间", "Created")}</th>}
            <th />
          </tr>
        </thead>
        <tbody>
          {runs.slice(0, compact ? 8 : 200).map((run) => (
            <tr key={run.id}>
              <td>
                <code>{shortId(run.id)}</code>
              </td>
              <td>
                <StatusPill status={run.status} />
              </td>
              <td>
                <span className="table-primary">
                  {stageLabel(run.stage, locale)}
                </span>
              </td>
              <td>{run.tool_calls}</td>
              <td>
                <strong className={run.score != null ? "score-value" : ""}>
                  {run.score == null ? "—" : Math.round(run.score)}
                </strong>
              </td>
              {!compact && (
                <td>{new Date(run.created_at).toLocaleString(locale)}</td>
              )}
              <td>
                <Link className="row-link" to={`/runs/${run.id}`}>
                  <ArrowRight size={14} />
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PageHeader({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow: string;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="page-header">
      <div>
        <span className="eyebrow">{eyebrow}</span>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action}
    </div>
  );
}

function PanelHeading({
  icon,
  title,
  detail,
  action,
}: {
  icon: ReactNode;
  title: string;
  detail?: string;
  action?: ReactNode;
}) {
  return (
    <div className="panel-heading">
      <div className="panel-heading__icon">{icon}</div>
      <div>
        <h3>{title}</h3>
        {detail && <span>{detail}</span>}
      </div>
      {action && <div className="panel-heading__action">{action}</div>}
    </div>
  );
}

function StatCard({
  icon,
  label,
  value,
  detail,
  accent,
}: {
  icon: ReactNode;
  label: string;
  value: ReactNode;
  detail: string;
  accent?: boolean;
}) {
  return (
    <article className={`stat-card ${accent ? "stat-card--accent" : ""}`}>
      <div className="stat-card__icon">{icon}</div>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </article>
  );
}

function StatusPill({ status }: { status: RunStatus }) {
  const { locale } = useLocale();
  const icon =
    status === "completed" ? (
      <CheckCircle2 />
    ) : status === "failed" ? (
      <XCircle />
    ) : status === "cancelled" ? (
      <X />
    ) : status === "queued" ? (
      <Clock3 />
    ) : (
      <CircleDot />
    );
  return (
    <span className={`status-pill status-pill--${status}`}>
      {icon}
      {statusLabel(status, locale)}
    </span>
  );
}

function BoundaryRow({
  label,
  good,
  value,
}: {
  label: string;
  good: boolean;
  value?: string;
}) {
  const { text } = useLocale();
  return (
    <div>
      <span>
        {good ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}
        {label}
      </span>
      <strong className={good ? "text-safe" : "text-warning"}>
        {value ?? (good ? text("就绪", "ready") : text("离线", "offline"))}
      </strong>
    </div>
  );
}

function Pressure({ value, label: caption }: { value: string; label: string }) {
  return (
    <div>
      <strong>{value}</strong>
      <span>{caption}</span>
    </div>
  );
}

function Metric({
  label: caption,
  value,
}: {
  label: string;
  value: ReactNode;
}) {
  return (
    <div>
      <span>{caption}</span>
      <strong>{value}</strong>
    </div>
  );
}

function MiniKpi({
  icon,
  label: caption,
  value,
}: {
  icon: ReactNode;
  label: string;
  value: ReactNode;
}) {
  return (
    <div className="mini-kpi">
      <span>{icon}</span>
      <div>
        <small>{caption}</small>
        <strong>{value}</strong>
      </div>
    </div>
  );
}

function Telemetry({
  icon,
  value,
  label: caption,
  danger,
}: {
  icon: ReactNode;
  value: ReactNode;
  label: string;
  danger?: boolean;
}) {
  return (
    <div className={`telemetry ${danger ? "telemetry--danger" : ""}`}>
      <span>{icon}</span>
      <strong>{value}</strong>
      <small>{caption}</small>
    </div>
  );
}

function Field({
  label: caption,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="field">
      <span>{caption}</span>
      {children}
      {hint && <small>{hint}</small>}
    </label>
  );
}

function Modal({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  return (
    <div className="modal-backdrop" role="presentation">
      <div className="modal" role="dialog" aria-modal="true">
        <div className="modal__head">
          <h2>{title}</h2>
          <button className="icon-button" onClick={onClose}>
            <X size={18} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

function EmptyState({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="empty-state">
      <Skull size={26} />
      <h3>{title}</h3>
      <p>{detail}</p>
    </div>
  );
}

function LoadingState() {
  const { text } = useLocale();
  return (
    <div className="loading-state">
      <div className="spinner" />
      <span>{text("正在读取归档…", "Reading the archive…")}</span>
    </div>
  );
}

function EventRow({ event }: { event: RunEvent }) {
  const { locale } = useLocale();
  return (
    <div className="event-row">
      <span className={`event-icon event-icon--${eventKind(event.kind)}`}>
        {eventIcon(event.kind)}
      </span>
      <div>
        <strong>{event.kind}</strong>
        <small>{eventSummary(event)}</small>
      </div>
      <time>{new Date(event.created_at).toLocaleTimeString(locale)}</time>
    </div>
  );
}

function eventKind(kind: string) {
  if (kind.includes("failed") || kind.includes("violation")) return "danger";
  if (kind.includes("completed") || kind.includes("evidence")) return "safe";
  if (kind.includes("hypothesis")) return "hypothesis";
  if (kind.includes("tool")) return "tool";
  return "neutral";
}

function eventIcon(kind: string) {
  if (kind.includes("hypothesis")) return <Lightbulb size={13} />;
  if (kind.includes("evidence")) return <Fingerprint size={13} />;
  if (kind.includes("tool")) return <SquareTerminal size={13} />;
  if (kind.includes("failed")) return <XCircle size={13} />;
  if (kind.includes("completed")) return <CheckCircle2 size={13} />;
  return <CircleDot size={13} />;
}

function eventSummary(event: RunEvent) {
  const payload = event.payload;
  if (payload.name) return String(payload.name);
  if (payload.stage) return String(payload.stage);
  if (payload.key) return String(payload.key);
  if (payload.status) return String(payload.status);
  return `event #${event.sequence}`;
}

function isTerminal(status?: RunStatus) {
  return (
    status === "completed" || status === "failed" || status === "cancelled"
  );
}

function shortId(value: string) {
  return value.slice(0, 8);
}

function taskCopy(task: Task, isChinese: boolean) {
  const localized = isChinese
    ? task.manifest.localizations?.["zh-CN"]
    : undefined;
  return {
    name: localized?.name ?? task.name,
    description: localized?.description ?? task.description,
  };
}

function providerLabel(provider: ModelProvider) {
  const labels: Record<ModelProvider, string> = {
    openai_responses: "OpenAI Responses API",
    anthropic: "Anthropic Messages API",
    openai_compatible: "OpenAI-compatible Chat Completions",
    ollama: "Ollama",
  };
  return labels[provider];
}

function providerDefaultUrl(provider: ModelProvider) {
  const urls: Record<ModelProvider, string> = {
    openai_responses: "https://api.openai.com/v1",
    anthropic: "https://api.anthropic.com/v1",
    openai_compatible: "https://api.example.com/v1",
    ollama: "http://host.docker.internal:11434",
  };
  return urls[provider];
}

function label(value: string, locale: "zh-CN" | "en" = "en") {
  const chinese: Record<string, string> = {
    functional_correctness: "功能正确性",
    root_cause_reasoning: "根因推理",
    database_forensics: "数据库取证",
    ci_oracle_analysis: "CI 可信度分析",
    evidence_quality: "证据质量",
    git_archaeology: "Git 考古",
    patch_engineering: "补丁工程质量",
    security: "安全",
    tool_resilience: "工具故障恢复",
    scope_control: "范围控制",
    investigation_report: "调查报告",
    efficiency: "效率",
  };
  if (locale === "zh-CN" && chinese[value]) return chinese[value];
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function statusLabel(status: RunStatus, locale: "zh-CN" | "en") {
  if (locale === "en") return status;
  const labels: Record<RunStatus, string> = {
    queued: "排队中",
    preparing: "准备中",
    running: "运行中",
    scoring: "评分中",
    completed: "已完成",
    failed: "失败",
    cancelled: "已取消",
  };
  return labels[status];
}

function stageLabel(stage: string, locale: "zh-CN" | "en") {
  if (locale === "en") return stage;
  const stages: Record<string, string> = {
    Queued: "排队中",
    Preparing: "正在准备",
    Running: "正在运行",
    Scoring: "正在评分",
    Completed: "已完成",
    Failed: "失败",
    Cancelled: "已取消",
  };
  return stages[stage] ?? stage;
}

function formatCompact(value?: number) {
  if (value == null) return "—";
  return Intl.NumberFormat(undefined, {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

function formatBytes(value?: number) {
  if (value == null) return "—";
  return `${Math.round(value / 1024 / 1024)} MB`;
}

function duration(
  start: string | null,
  end: string | null,
  locale: "zh-CN" | "en" = "en",
) {
  if (!start) return "—";
  const seconds = Math.max(
    0,
    (new Date(end ?? Date.now()).getTime() - new Date(start).getTime()) / 1000,
  );
  if (seconds < 60)
    return locale === "zh-CN"
      ? `${Math.round(seconds)} 秒`
      : `${Math.round(seconds)}s`;
  const minutes = Math.floor(seconds / 60);
  return locale === "zh-CN"
    ? `${Math.floor(minutes / 60)} 小时 ${minutes % 60} 分`
    : `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}
