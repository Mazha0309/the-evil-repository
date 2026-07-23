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
import type { Run, RunEvent, RunStatus, Task } from "./lib/types";

const InvestigationGraphView = lazy(
  () => import("./components/InvestigationGraph"),
);
const ScoreRadar = lazy(() => import("./components/ScoreRadar"));

export default function App() {
  const [mobileNav, setMobileNav] = useState(false);
  return (
    <div className="app-shell">
      <aside className={`sidebar ${mobileNav ? "sidebar--open" : ""}`}>
        <div className="brand">
          <div className="brand__mark">
            <Skull size={22} strokeWidth={1.8} />
          </div>
          <div>
            <strong>The Evil Repository</strong>
            <span>EvilBench Control Plane</span>
          </div>
        </div>
        <nav className="nav">
          <NavItem to="/" icon={<Home size={17} />} label="Overview" end />
          <NavItem to="/scenarios" icon={<Blocks size={17} />} label="Scenarios" />
          <NavItem to="/models" icon={<Bot size={17} />} label="Model profiles" />
          <NavItem to="/runs" icon={<Activity size={17} />} label="Runs" />
          <NavItem to="/settings" icon={<Settings size={17} />} label="Settings" />
        </nav>
        <div className="sidebar__footer">
          <span className="status-dot status-dot--safe" />
          <div>
            <strong>Rootless boundary</strong>
            <small>Local control plane</small>
          </div>
        </div>
      </aside>
      {mobileNav && <button className="nav-scrim" onClick={() => setMobileNav(false)} />}
      <main className="main">
        <header className="topbar">
          <button className="icon-button topbar__menu" onClick={() => setMobileNav(true)}>
            <Menu size={19} />
          </button>
          <div className="topbar__context">
            <span className="eyebrow">AI AGENT CTF / INCIDENT RESPONSE</span>
            <span className="topbar__divider" />
            <span>localhost</span>
          </div>
          <div className="topbar__actions">
            <a
              className="quiet-link"
              href="https://www.gnu.org/licenses/agpl-3.0.html"
              target="_blank"
              rel="noreferrer"
            >
              AGPLv3 <ExternalLink size={12} />
            </a>
            <Link className="button button--small" to="/runs/new">
              <Play size={14} fill="currentColor" /> New run
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
    <NavLink to={to} end={end} className={({ isActive }) => (isActive ? "active" : "")}>
      {icon}
      <span>{label}</span>
      <ChevronRight className="nav__chevron" size={14} />
    </NavLink>
  );
}

function DashboardPage() {
  const summary = useQuery({ queryKey: ["summary"], queryFn: api.summary, refetchInterval: 5_000 });
  const runs = useQuery({ queryKey: ["runs"], queryFn: api.runs, refetchInterval: 5_000 });
  const tasks = useQuery({ queryKey: ["tasks"], queryFn: api.tasks });
  const data = summary.data;
  return (
    <>
      <PageHeader
        eyebrow="CONTROL ROOM"
        title="Evidence under pressure."
        description="Watch models investigate hostile repositories, dirty data, and poisoned authority without crossing the sandbox boundary."
        action={
          <Link className="button" to="/runs/new">
            <Play size={15} fill="currentColor" /> Launch investigation
          </Link>
        }
      />
      <div className="stat-grid">
        <StatCard
          icon={<FlaskConical />}
          label="Scenarios"
          value={data?.tasks ?? "—"}
          detail="Versioned SDK packages"
        />
        <StatCard
          icon={<Bot />}
          label="Candidate models"
          value={data?.models ?? "—"}
          detail="Provider profiles"
        />
        <StatCard
          icon={<Activity />}
          label="Active runs"
          value={data?.active_runs ?? "—"}
          detail={`${data?.total_runs ?? 0} total investigations`}
          accent={Boolean(data?.active_runs)}
        />
        <StatCard
          icon={<Radar />}
          label="Average score"
          value={data?.average_score == null ? "—" : Math.round(data.average_score)}
          detail="out of 1,200"
        />
      </div>
      <div className="dashboard-grid">
        <section className="panel panel--wide">
          <PanelHeading
            icon={<Activity size={16} />}
            title="Recent investigations"
            detail="Live state from the Runner queue"
            action={<Link to="/runs">View all</Link>}
          />
          <RunTable runs={runs.data ?? []} compact />
        </section>
        <section className="panel">
          <PanelHeading
            icon={<ShieldCheck size={16} />}
            title="Boundary posture"
            detail="Current control-plane readiness"
          />
          <div className="boundary-list">
            <BoundaryRow label="Rootless Docker" good={Boolean(data?.docker_ready)} />
            <BoundaryRow label="Runner worker" good={Boolean(data?.runner_enabled)} />
            <BoundaryRow label="Candidate network" good value="none" />
            <BoundaryRow label="Host bind mounts" good value="denied" />
            <BoundaryRow label="Provider secrets" good value="control plane only" />
          </div>
        </section>
        <section className="panel panel--wide scenario-spotlight">
          <div className="scenario-spotlight__badge">
            <Skull size={28} />
          </div>
          <div className="scenario-spotlight__copy">
            <span className="eyebrow">CANONICAL SCENARIO</span>
            <h2>{tasks.data?.[0]?.name ?? "The Terminal Repository"}</h2>
            <p>
              Two Git histories. A broken CI oracle. Two dirty databases. A synthetic internet
              full of authority injection. One tiny correct patch.
            </p>
          </div>
          <div className="pressure-grid">
            <Pressure value="5K" label="files" />
            <Pressure value="2K" label="commits" />
            <Pressure value="100MB" label="offline docs" />
            <Pressure value="180m" label="hard limit" />
          </div>
          <Link className="button button--ghost" to="/scenarios">
            Inspect scenario <ArrowRight size={15} />
          </Link>
        </section>
      </div>
    </>
  );
}

function ScenariosPage() {
  const tasks = useQuery({ queryKey: ["tasks"], queryFn: api.tasks });
  return (
    <>
      <PageHeader
        eyebrow="SCENARIO SDK"
        title="Hostile worlds, versioned."
        description="Each scenario owns its repositories, databases, injections, failure scripts, hidden judge, replay contract, and offline internet."
      />
      <div className="card-stack">
        {(tasks.data ?? []).map((task) => (
          <ScenarioCard key={task.id} task={task} />
        ))}
        {!tasks.isLoading && !tasks.data?.length && (
          <EmptyState title="No scenarios loaded" detail="Add a valid Scenario SDK directory." />
        )}
      </div>
    </>
  );
}

function ScenarioCard({ task }: { task: Task }) {
  const pressure = task.manifest.context_pressure;
  const scoring = task.manifest.scoring ?? {};
  return (
    <article className="scenario-card">
      <div className="scenario-card__icon">
        <Skull size={30} />
      </div>
      <div className="scenario-card__main">
        <div className="scenario-card__title">
          <div>
            <span className="eyebrow">SCENARIO / {task.version}</span>
            <h2>{task.name}</h2>
          </div>
          <span className="pill pill--lime">enabled</span>
        </div>
        <p>{task.description}</p>
        <div className="tag-row">
          <span><GitBranch size={13} /> cross-repository</span>
          <span><Database size={13} /> dirty database</span>
          <span><ShieldAlert size={13} /> prompt injection</span>
          <span><Network size={13} /> offline internet</span>
          <span><TimerReset size={13} /> scripted faults</span>
        </div>
        <div className="scenario-metrics">
          <Metric label="Files" value={formatCompact(pressure?.target_files)} />
          <Metric label="Git commits" value={formatCompact(pressure?.target_git_commits)} />
          <Metric label="Mirror" value={formatBytes(pressure?.target_mirror_bytes)} />
          <Metric
            label="Maximum score"
            value={Object.values(scoring).reduce((sum, value) => sum + value, 0) || 1_200}
          />
        </div>
      </div>
      <div className="scenario-card__actions">
        <a
          className="button button--ghost"
          href={`http://127.0.0.1:8080/api/v1/tasks/${task.id}/export`}
        >
          <Download size={14} /> Metadata
        </a>
        <Link className="button" to={`/runs/new?task=${task.id}`}>
          <Play size={14} fill="currentColor" /> Run
        </Link>
      </div>
    </article>
  );
}

function ModelsPage() {
  const queryClient = useQueryClient();
  const models = useQuery({ queryKey: ["models"], queryFn: api.models });
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");
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
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["models"] }),
  });
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    create.mutate({
      name: data.get("name"),
      provider: data.get("provider"),
      base_url: data.get("base_url"),
      model_id: data.get("model_id"),
      api_key: data.get("api_key") || null,
      native_tools: data.get("native_tools") === "on",
      parameters: { temperature: 0 },
      enabled: true,
    });
  };
  return (
    <>
      <PageHeader
        eyebrow="MODEL REGISTRY"
        title="Candidates and judges."
        description="Provider credentials are encrypted in the control plane and never enter a candidate sandbox or run archive."
        action={
          <button className="button" onClick={() => setOpen(true)}>
            <Plus size={15} /> Add profile
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
                <span>{model.provider.replace("_", " ")}</span>
              </div>
              <button
                className="icon-button icon-button--danger"
                onClick={() => remove.mutate(model.id)}
                title="Delete model profile"
              >
                <Trash2 size={15} />
              </button>
            </div>
            <dl>
              <div><dt>Model</dt><dd>{model.model_id}</dd></div>
              <div><dt>Endpoint</dt><dd>{model.base_url}</dd></div>
              <div>
                <dt>Tool protocol</dt>
                <dd>{model.native_tools ? "Native function calls" : "JSON fallback"}</dd>
              </div>
              <div>
                <dt>Credential</dt>
                <dd className={model.has_api_key ? "text-safe" : ""}>
                  {model.has_api_key ? "Encrypted" : "Not required"}
                </dd>
              </div>
            </dl>
          </article>
        ))}
        {!models.isLoading && !models.data?.length && (
          <button className="model-card model-card--empty" onClick={() => setOpen(true)}>
            <Plus size={28} />
            <strong>Add your first model</strong>
            <span>OpenAI-compatible or Ollama</span>
          </button>
        )}
      </div>
      {open && (
        <Modal title="Add model profile" onClose={() => setOpen(false)}>
          <form className="form" onSubmit={submit}>
            <Field label="Profile name"><input name="name" required placeholder="Claude Sonnet" /></Field>
            <Field label="Provider">
              <select name="provider" defaultValue="openai_compatible">
                <option value="openai_compatible">OpenAI-compatible API</option>
                <option value="ollama">Ollama</option>
              </select>
            </Field>
            <Field label="Base URL">
              <input name="base_url" type="url" required placeholder="https://api.example.com/v1" />
            </Field>
            <Field label="Model ID"><input name="model_id" required placeholder="model-name" /></Field>
            <Field label="API key" hint="Encrypted at rest; leave blank for Ollama.">
              <input name="api_key" type="password" autoComplete="new-password" />
            </Field>
            <label className="check-row">
              <input name="native_tools" type="checkbox" defaultChecked />
              <span>
                <strong>Native function calling</strong>
                <small>Disable to use EvilBench's strict JSON fallback protocol.</small>
              </span>
            </label>
            {error && <div className="inline-error">{error}</div>}
            <div className="modal__actions">
              <button className="button button--ghost" type="button" onClick={() => setOpen(false)}>
                Cancel
              </button>
              <button className="button" disabled={create.isPending}>
                <KeyRound size={14} /> Save encrypted profile
              </button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}

function RunsPage() {
  const runs = useQuery({ queryKey: ["runs"], queryFn: api.runs, refetchInterval: 4_000 });
  return (
    <>
      <PageHeader
        eyebrow="RUN ARCHIVE"
        title="Every investigation, replayable."
        description="Compare outcomes, graph quality, security posture, resource use, and hypothesis evolution."
        action={
          <Link className="button" to="/runs/new">
            <Play size={15} fill="currentColor" /> New run
          </Link>
        }
      />
      <section className="panel">
        <div className="toolbar">
          <span><ListFilter size={14} /> Latest 200 runs</span>
          <span className="toolbar__count">{runs.data?.length ?? 0} records</span>
        </div>
        <RunTable runs={runs.data ?? []} />
      </section>
    </>
  );
}

function NewRunPage() {
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
        eyebrow="NEW INVESTIGATION"
        title="Drop a model into hell."
        description="A fresh Rootless Docker workspace will be generated from the selected Scenario and destroyed after grading."
      />
      <form className="run-builder" onSubmit={submit}>
        <section className="panel">
          <PanelHeading icon={<Blocks size={16} />} title="Scenario" detail="Versioned world package" />
          <div className="choice-grid">
            {(tasks.data ?? []).map((task, index) => (
              <label className="choice-card" key={task.id}>
                <input type="radio" name="task_id" value={task.id} defaultChecked={index === 0} />
                <div className="choice-card__check"><CheckCircle2 size={16} /></div>
                <Skull size={24} />
                <strong>{task.name}</strong>
                <span>{task.description}</span>
              </label>
            ))}
          </div>
        </section>
        <section className="panel">
          <PanelHeading icon={<Bot size={16} />} title="Models" detail="Candidate and optional judge" />
          <div className="form-grid">
            <Field label="Candidate">
              <select name="candidate_model_id" required defaultValue="">
                <option value="" disabled>Select a candidate</option>
                {(models.data ?? []).map((model) => (
                  <option value={model.id} key={model.id}>{model.name} · {model.model_id}</option>
                ))}
              </select>
            </Field>
            <Field label="Independent judge" hint="Optional for the terminal scenario.">
              <select name="judge_model_id" defaultValue="">
                <option value="">Deterministic judge only</option>
                {(models.data ?? []).map((model) => (
                  <option value={model.id} key={model.id}>{model.name}</option>
                ))}
              </select>
            </Field>
          </div>
          {!models.data?.length && (
            <div className="callout callout--warning">
              <AlertTriangle size={17} />
              <span>Add a model profile before launching a run.</span>
              <Link to="/models">Open model registry</Link>
            </div>
          )}
        </section>
        <section className="panel">
          <PanelHeading icon={<Gauge size={16} />} title="Budgets" detail="Soft score curve and hard stop" />
          <div className="budget-grid">
            <Field label="Soft time (seconds)"><input name="soft_seconds" type="number" defaultValue={5400} min={60} /></Field>
            <Field label="Hard time (seconds)"><input name="hard_seconds" type="number" defaultValue={10800} min={300} /></Field>
            <Field label="Soft tool calls"><input name="soft_tool_calls" type="number" defaultValue={500} min={10} /></Field>
            <Field label="Hard tool calls"><input name="hard_tool_calls" type="number" defaultValue={1000} min={20} /></Field>
          </div>
        </section>
        <section className="launch-strip">
          <div>
            <ShieldCheck size={20} />
            <span>
              <strong>Fresh isolated environment</strong>
              Rootless · network none · no host mounts · capabilities dropped
            </span>
          </div>
          {error && <span className="text-danger">{error}</span>}
          <button className="button button--large" disabled={!models.data?.length || create.isPending}>
            <Zap size={16} fill="currentColor" /> Create run
          </button>
        </section>
      </form>
    </>
  );
}

function RunDetailPage() {
  const { runId = "" } = useParams();
  const [tab, setTab] = useState<"overview" | "graph" | "audit" | "score">("overview");
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
  if (!data) return <EmptyState title="Run not found" detail="The archive does not contain this run." />;
  const dimensions = data.scorecard.dimensions ?? {};
  return (
    <>
      <div className="run-hero">
        <div>
          <div className="run-hero__meta">
            <StatusPill status={data.status} />
            <span>{shortId(data.id)}</span>
            <span>{new Date(data.created_at).toLocaleString()}</span>
          </div>
          <h1>{data.stage}</h1>
          <p>
            {data.status === "completed"
              ? "The hidden judge pipeline has archived this investigation."
              : "The Runner is streaming observable investigation state from the isolated candidate."}
          </p>
        </div>
        <div className="run-score">
          <span>Score</span>
          <strong>{data.score == null ? "—" : Math.round(data.score)}</strong>
          <small>/ {data.scorecard.maximum ?? 1_200}</small>
        </div>
      </div>
      <div className="run-kpis">
        <MiniKpi icon={<SquareTerminal />} label="Tool calls" value={data.tool_calls} />
        <MiniKpi icon={<Braces />} label="Input tokens" value={formatCompact(data.input_tokens)} />
        <MiniKpi icon={<Bot />} label="Output tokens" value={formatCompact(data.output_tokens)} />
        <MiniKpi
          icon={<Clock3 />}
          label="Elapsed"
          value={duration(data.started_at, data.completed_at)}
        />
        <MiniKpi
          icon={<Lightbulb />}
          label="Hypotheses"
          value={graph.data?.hypotheses.length ?? 0}
        />
        <MiniKpi icon={<Fingerprint />} label="Evidence" value={graph.data?.evidence.length ?? 0} />
      </div>
      <div className="tabs">
        <button className={tab === "overview" ? "active" : ""} onClick={() => setTab("overview")}>
          <Activity size={14} /> Overview
        </button>
        <button className={tab === "graph" ? "active" : ""} onClick={() => setTab("graph")}>
          <Network size={14} /> Hypothesis graph
        </button>
        <button className={tab === "audit" ? "active" : ""} onClick={() => setTab("audit")}>
          <ScrollText size={14} /> Audit
        </button>
        <button className={tab === "score" ? "active" : ""} onClick={() => setTab("score")}>
          <Radar size={14} /> Judge
        </button>
      </div>
      {tab === "overview" && <RunOverview run={data} events={events.data ?? []} />}
      {tab === "graph" && (
        <section className="panel panel--flush">
          <div className="graph-header">
            <div>
              <span className="eyebrow">OBSERVABLE INVESTIGATION LEDGER</span>
              <h2>Hypothesis Graph / Truth Tree</h2>
            </div>
            <div className="graph-legend">
              <span><i className="legend-dot legend-dot--evidence" /> Evidence</span>
              <span><i className="legend-dot legend-dot--hypothesis" /> Hypothesis</span>
              <span><i className="legend-line legend-line--conflict" /> Contradicts</span>
            </div>
          </div>
          <Suspense fallback={<LoadingState />}>
            <InvestigationGraphView
              graph={graph.data ?? { hypotheses: [], revisions: [], evidence: [], edges: [] }}
            />
          </Suspense>
        </section>
      )}
      {tab === "audit" && <AuditTimeline events={events.data ?? []} />}
      {tab === "score" && (
        <div className="judge-grid">
          <section className="panel">
            <PanelHeading icon={<Radar size={16} />} title="1,200-point profile" detail="Hidden judge dimensions" />
            {Object.keys(dimensions).length ? (
              <Suspense fallback={<LoadingState />}>
                <ScoreRadar dimensions={dimensions} />
              </Suspense>
            ) : (
              <EmptyState title="Waiting for the judge" detail="Scores appear after archive." />
            )}
          </section>
          <section className="panel score-list">
            <PanelHeading icon={<Gauge size={16} />} title="Dimension ledger" detail="Points and hard caps" />
            {Object.entries(dimensions)
              .sort(([, a], [, b]) => b.maximum - a.maximum)
              .map(([key, metric]) => (
                <div className="score-row" key={key}>
                  <div>
                    <strong>{metric.label || label(key)}</strong>
                    <span>{metric.score} / {metric.maximum}</span>
                  </div>
                  <div className="score-bar">
                    <i style={{ width: `${(metric.score / metric.maximum) * 100}%` }} />
                  </div>
                </div>
              ))}
            {data.scorecard.caps?.map((cap) => (
              <div className="callout callout--danger" key={cap.reason}>
                <OctagonAlert size={16} />
                <span>{cap.reason}</span>
                <strong>cap {cap.max}</strong>
              </div>
            ))}
          </section>
        </div>
      )}
      <div className="run-footer-actions">
        <a className="button button--ghost" href={api.reportUrl(data.id)}>
          <Download size={14} /> Export report
        </a>
        {!isTerminal(data.status) && (
          <button className="button button--danger" onClick={() => void api.cancelRun(data.id)}>
            <X size={14} /> Cancel run
          </button>
        )}
      </div>
    </>
  );
}

function RunOverview({ run, events }: { run: Run; events: RunEvent[] }) {
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
        <PanelHeading icon={<Activity size={16} />} title="Latest activity" detail="Newest event first" />
        <div className="event-list">
          {latest.map((event) => (
            <EventRow event={event} key={event.id} />
          ))}
          {!latest.length && <EmptyState title="No events yet" detail="The Runner is preparing the Scenario." />}
        </div>
      </section>
      <div className="side-stack">
        <section className="panel">
          <PanelHeading icon={<ShieldAlert size={16} />} title="Adversarial telemetry" />
          <div className="telemetry-grid">
            <Telemetry
              icon={violations.length ? <XCircle /> : <ShieldCheck />}
              value={violations.length}
              label="boundary violations"
              danger={Boolean(violations.length)}
            />
            <Telemetry icon={<TimerReset />} value={faults.length} label="scripted faults encountered" />
          </div>
        </section>
        <section className="panel">
          <PanelHeading icon={<Box size={16} />} title="Isolation envelope" />
          <div className="tag-column">
            <span><ShieldCheck size={13} /> Rootless daemon</span>
            <span><Network size={13} /> network_mode: none</span>
            <span><Database size={13} /> PostgreSQL via Unix socket</span>
            <span><FileCode2 size={13} /> ephemeral workspace</span>
            <span><KeyRound size={13} /> no provider secrets</span>
          </div>
        </section>
        {run.error && (
          <section className="panel panel--danger">
            <PanelHeading icon={<OctagonAlert size={16} />} title="Runner error" />
            <pre>{run.error}</pre>
          </section>
        )}
      </div>
    </div>
  );
}

function AuditTimeline({ events }: { events: RunEvent[] }) {
  return (
    <section className="panel">
      <PanelHeading
        icon={<ScrollText size={16} />}
        title="Immutable event stream"
        detail={`${events.length} events`}
      />
      <div className="audit-list">
        {events.map((event) => (
          <details key={event.id} className="audit-event">
            <summary>
              <span className={`event-icon event-icon--${eventKind(event.kind)}`}>
                {eventIcon(event.kind)}
              </span>
              <span>
                <strong>{event.kind}</strong>
                <small>#{event.sequence} · {new Date(event.created_at).toLocaleTimeString()}</small>
              </span>
              <code>{event.payload.name ? String(event.payload.name) : ""}</code>
            </summary>
            <pre>{JSON.stringify(event.payload, null, 2)}</pre>
          </details>
        ))}
      </div>
    </section>
  );
}

function SettingsPage() {
  return (
    <>
      <PageHeader
        eyebrow="LOCAL CONTROL PLANE"
        title="Security is configuration."
        description="The UI intentionally exposes only non-secret posture. Runtime secrets remain server-side."
      />
      <div className="settings-grid">
        <section className="panel">
          <PanelHeading icon={<ShieldCheck size={16} />} title="Required sandbox profile" />
          <div className="config-code">
            <code>Docker context</code><strong>rootless</strong>
            <code>Network</code><strong>none</strong>
            <code>Root filesystem</code><strong>read-only</strong>
            <code>Linux capabilities</code><strong>ALL dropped</strong>
            <code>Privilege escalation</code><strong>disabled</strong>
            <code>Host mounts</code><strong>none</strong>
          </div>
        </section>
        <section className="panel">
          <PanelHeading icon={<GitCommitHorizontal size={16} />} title="Open design" />
          <p className="panel-copy">
            Scenario SDK contracts, threat assumptions, scoring, and UI behavior are maintained
            in <code>DESIGN.md</code> under AGPL-3.0-only.
          </p>
          <a
            className="button button--ghost"
            href="https://github.com/"
            target="_blank"
            rel="noreferrer"
          >
            Repository not published yet <ExternalLink size={14} />
          </a>
        </section>
      </div>
    </>
  );
}

function RunTable({ runs, compact = false }: { runs: Run[]; compact?: boolean }) {
  if (!runs.length) return <EmptyState title="No investigations yet" detail="Create a run to populate the archive." />;
  return (
    <div className="table-scroll">
      <table className="data-table">
        <thead>
          <tr>
            <th>Run</th><th>Status</th><th>Stage</th><th>Tools</th><th>Score</th>
            {!compact && <th>Created</th>}<th />
          </tr>
        </thead>
        <tbody>
          {runs.slice(0, compact ? 8 : 200).map((run) => (
            <tr key={run.id}>
              <td><code>{shortId(run.id)}</code></td>
              <td><StatusPill status={run.status} /></td>
              <td><span className="table-primary">{run.stage}</span></td>
              <td>{run.tool_calls}</td>
              <td>
                <strong className={run.score != null ? "score-value" : ""}>
                  {run.score == null ? "—" : Math.round(run.score)}
                </strong>
              </td>
              {!compact && <td>{new Date(run.created_at).toLocaleString()}</td>}
              <td><Link className="row-link" to={`/runs/${run.id}`}><ArrowRight size={14} /></Link></td>
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
      <div><h3>{title}</h3>{detail && <span>{detail}</span>}</div>
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
      <span>{label}</span><strong>{value}</strong><small>{detail}</small>
    </article>
  );
}

function StatusPill({ status }: { status: RunStatus }) {
  const icon =
    status === "completed" ? <CheckCircle2 /> :
      status === "failed" ? <XCircle /> :
        status === "cancelled" ? <X /> :
          status === "queued" ? <Clock3 /> : <CircleDot />;
  return <span className={`status-pill status-pill--${status}`}>{icon}{status}</span>;
}

function BoundaryRow({ label, good, value }: { label: string; good: boolean; value?: string }) {
  return (
    <div><span>{good ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}{label}</span>
      <strong className={good ? "text-safe" : "text-warning"}>{value ?? (good ? "ready" : "offline")}</strong>
    </div>
  );
}

function Pressure({ value, label: caption }: { value: string; label: string }) {
  return <div><strong>{value}</strong><span>{caption}</span></div>;
}

function Metric({ label: caption, value }: { label: string; value: ReactNode }) {
  return <div><span>{caption}</span><strong>{value}</strong></div>;
}

function MiniKpi({ icon, label: caption, value }: { icon: ReactNode; label: string; value: ReactNode }) {
  return <div className="mini-kpi"><span>{icon}</span><div><small>{caption}</small><strong>{value}</strong></div></div>;
}

function Telemetry({ icon, value, label: caption, danger }: { icon: ReactNode; value: ReactNode; label: string; danger?: boolean }) {
  return <div className={`telemetry ${danger ? "telemetry--danger" : ""}`}><span>{icon}</span><strong>{value}</strong><small>{caption}</small></div>;
}

function Field({ label: caption, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return <label className="field"><span>{caption}</span>{children}{hint && <small>{hint}</small>}</label>;
}

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return (
    <div className="modal-backdrop" role="presentation">
      <div className="modal" role="dialog" aria-modal="true">
        <div className="modal__head"><h2>{title}</h2><button className="icon-button" onClick={onClose}><X size={18} /></button></div>
        {children}
      </div>
    </div>
  );
}

function EmptyState({ title, detail }: { title: string; detail: string }) {
  return <div className="empty-state"><Skull size={26} /><h3>{title}</h3><p>{detail}</p></div>;
}

function LoadingState() {
  return <div className="loading-state"><div className="spinner" /><span>Reading the archive…</span></div>;
}

function EventRow({ event }: { event: RunEvent }) {
  return (
    <div className="event-row">
      <span className={`event-icon event-icon--${eventKind(event.kind)}`}>{eventIcon(event.kind)}</span>
      <div><strong>{event.kind}</strong><small>{eventSummary(event)}</small></div>
      <time>{new Date(event.created_at).toLocaleTimeString()}</time>
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
  return status === "completed" || status === "failed" || status === "cancelled";
}

function shortId(value: string) {
  return value.slice(0, 8);
}

function label(value: string) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (character) => character.toUpperCase());
}

function formatCompact(value?: number) {
  if (value == null) return "—";
  return Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

function formatBytes(value?: number) {
  if (value == null) return "—";
  return `${Math.round(value / 1024 / 1024)} MB`;
}

function duration(start: string | null, end: string | null) {
  if (!start) return "—";
  const seconds = Math.max(0, (new Date(end ?? Date.now()).getTime() - new Date(start).getTime()) / 1000);
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = Math.floor(seconds / 60);
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}
