import {
  Activity,
  AlertTriangle,
  Bot,
  CheckCircle2,
  CircleDot,
  FileText,
  Fingerprint,
  Gauge,
  Lightbulb,
  Pause,
  Radio,
  ShieldAlert,
  SquareTerminal,
  TimerReset,
  XCircle,
} from "lucide-react";
import { useEffect, useState } from "react";
import {
  analyzeRunEvents,
  cleanPreview,
  completionProgress,
  type LivePhase,
} from "../lib/live";
import { useLocale } from "../lib/i18n";
import type {
  CompletionSpec,
  IncidentSpec,
  InvestigationGraph,
  Run,
  RunEvent,
} from "../lib/types";

interface LiveRunMonitorProps {
  run: Run;
  events: RunEvent[];
  graph: InvestigationGraph;
  completion?: CompletionSpec;
  incident?: IncidentSpec;
}

export default function LiveRunMonitor({
  run,
  events,
  graph,
  completion,
  incident,
}: LiveRunMonitorProps) {
  const { locale, text } = useLocale();
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, []);

  const pauseRequested = run.config.pause_requested === true;
  const analysis = analyzeRunEvents(events, run.status, now, pauseRequested);
  const progress = completionProgress(events, graph, completion);
  const incidentTelemetry = analyzeIncidentTelemetry(events);
  const softBudgetWarning = [...events]
    .reverse()
    .find((event) => event.kind === "run.soft_budget_warning");
  const latestProtocolRepair = [...events]
    .reverse()
    .find((event) => event.kind === "provider.tool_call_invalid");
  const wallElapsedMs = run.started_at
    ? Math.max(
        0,
        (run.completed_at ? new Date(run.completed_at).getTime() : now) -
          new Date(run.started_at).getTime(),
      )
    : 0;
  const activeElapsedMs = Math.max(0, wallElapsedMs - analysis.pausedMs);
  const hardCalls = numericConfig(run.config.hard_tool_calls);
  const softCalls = numericConfig(run.config.soft_tool_calls);
  const hardSeconds = numericConfig(run.config.hard_seconds);
  const softSeconds = numericConfig(run.config.soft_seconds);
  const hardProviderRequests = numericConfig(
    run.config.hard_provider_requests,
  );
  const softProviderRequests = numericConfig(
    run.config.soft_provider_requests,
  );
  const hardTokens = numericConfig(run.config.hard_total_tokens);
  const softTokens = numericConfig(run.config.soft_total_tokens);
  const totalTokens = run.input_tokens + run.output_tokens;
  const providerRequests = events.reduce(
    (maximum, event) =>
      Math.max(
        maximum,
        Number(
          event.payload.provider_requests_total ??
            event.payload.provider_requests ??
            0,
        ) || 0,
      ),
    0,
  );
  const phaseAgeMs = analysis.phaseSince
    ? Math.max(0, now - new Date(analysis.phaseSince).getTime())
    : 0;
  const waitingTooLong =
    !terminalPhase(analysis.phase) &&
    analysis.phase !== "paused" &&
    analysis.lastEventAgeMs > 45_000;
  const operationDuration = analysis.operation?.pending
    ? Math.max(0, now - new Date(analysis.operation.call.created_at).getTime())
    : analysis.operation?.durationMs;
  const latestHypotheses = [...graph.hypotheses]
    .sort(
      (left, right) =>
        new Date(right.updated_at).getTime() -
        new Date(left.updated_at).getTime(),
    )
    .slice(0, 6);
  const maximumToolCount = Math.max(
    1,
    ...analysis.toolBreakdown.map(([, count]) => count),
  );

  return (
    <div className="live-monitor">
      <section
        className={`panel live-stage live-stage--${analysis.phase} ${
          waitingTooLong ? "live-stage--waiting" : ""
        }`}
      >
        <div className="live-stage__header">
          <span className="live-signal">
            <i />
            {terminalPhase(analysis.phase)
              ? text("运行归档", "RUN ARCHIVE")
              : text("实时遥测", "LIVE TELEMETRY")}
          </span>
          <span>
            {analysis.lastEvent
              ? text(
                  `事件 #${analysis.lastEvent.sequence} · ${updatedLabel(
                    analysis.lastEventAgeMs,
                    true,
                  )}`,
                  `event #${analysis.lastEvent.sequence} · ${updatedLabel(
                    analysis.lastEventAgeMs,
                    false,
                  )}`,
                )
              : text("等待首个事件", "waiting for the first event")}
          </span>
        </div>
        <div className="live-stage__state">
          <span className="live-stage__icon">{phaseIcon(analysis.phase)}</span>
          <div>
            <span className="eyebrow">{text("当前状态", "CURRENT STATE")}</span>
            <h2>{phaseLabel(analysis.phase, locale)}</h2>
            <p>
              {phaseDetail(
                analysis.phase,
                phaseAgeMs,
                waitingTooLong,
                analysis.lastEvent,
                locale,
              )}
            </p>
          </div>
        </div>
        {analysis.operation && (
          <div className="live-operation">
            <div className="live-operation__title">
              <span>
                <SquareTerminal size={13} />
                {analysis.operation.pending
                  ? text("正在执行工具", "Executing tool")
                  : text("最近一次工具", "Latest tool")}
              </span>
              <strong>{analysis.operation.name}</strong>
              <code>{formatDuration(operationDuration ?? 0, locale)}</code>
            </div>
            <pre>{analysis.operation.summary}</pre>
            {analysis.operation.result && (
              <div className="live-operation__result">
                <span
                  className={
                    String(analysis.operation.result.payload.status) === "ok"
                      ? "text-safe"
                      : "text-danger"
                  }
                >
                  {String(
                    analysis.operation.result.payload.status ?? "unknown",
                  )}
                  {analysis.operation.result.payload.exit_code != null
                    ? ` · exit ${String(
                        analysis.operation.result.payload.exit_code,
                      )}`
                    : ""}
                </span>
                {analysis.operation.output && (
                  <details>
                    <summary>
                      {text("查看结果预览", "Inspect result preview")}
                    </summary>
                    <pre>{analysis.operation.output}</pre>
                  </details>
                )}
              </div>
            )}
          </div>
        )}
        {waitingTooLong && (
          <div className="live-warning">
            <AlertTriangle size={14} />
            <span>
              {text(
                "事件流超过 45 秒没有推进；可能正在等待 Provider、工具超时或 Runner 异常。",
                "The event stream has not advanced for 45 seconds; the Provider, a tool timeout, or the Runner may be blocking.",
              )}
            </span>
          </div>
        )}
        {softBudgetWarning && (
          <div className="live-warning">
            <Gauge size={14} />
            <span>{softBudgetDetail(softBudgetWarning, locale)}</span>
          </div>
        )}
        {latestProtocolRepair && (
          <div className="live-warning">
            <ShieldAlert size={14} />
            <span>
              {text(
                `Provider 曾返回不完整的工具参数；Runner 已隔离且未执行，并发起修复轮次（累计 ${analysis.protocolRepairs} 次）。`,
                `The Provider returned incomplete tool arguments; the Runner quarantined them without execution and requested a repair turn (${analysis.protocolRepairs} total).`,
              )}
            </span>
          </div>
        )}
      </section>

      <div className="live-grid live-grid--top">
        <section className="panel live-card">
          <MonitorHeading
            icon={<Gauge size={15} />}
            title={text("预算消耗", "Budget burn")}
            detail={text("软限制 / 硬限制", "soft limit / hard limit")}
          />
          <LiveMeter
            label={text("工具调用", "Tool calls")}
            value={run.tool_calls}
            soft={softCalls}
            hard={hardCalls}
            display={`${run.tool_calls} / ${hardCalls || "—"}`}
          />
          <LiveMeter
            label={text("有效运行时间", "Active time")}
            value={activeElapsedMs / 1_000}
            soft={softSeconds}
            hard={hardSeconds}
            display={formatDuration(activeElapsedMs, locale)}
          />
          <LiveMeter
            label={text("Provider 请求", "Provider requests")}
            value={providerRequests}
            soft={softProviderRequests}
            hard={hardProviderRequests}
            display={`${providerRequests} / ${hardProviderRequests || "—"}`}
          />
          {hardTokens > 0 && (
            <LiveMeter
              label={text("Token 总量", "Total tokens")}
              value={totalTokens}
              soft={softTokens}
              hard={hardTokens}
              display={`${compact(totalTokens)} / ${compact(hardTokens)}`}
            />
          )}
          <div className="live-stat-row">
            <span>
              <Bot size={13} />
              {text("输入", "Input")}{" "}
              <strong>{compact(run.input_tokens)}</strong>
            </span>
            <span>
              <Activity size={13} />
              {text("输出", "Output")}{" "}
              <strong>{compact(run.output_tokens)}</strong>
            </span>
            <span>
              <TimerReset size={13} />
              <strong>{analysis.toolRatePerMinute.toFixed(1)}</strong> / min
            </span>
            {analysis.pausedMs > 0 && (
              <span>
                <Pause size={13} />
                {text("已暂停", "Paused")}{" "}
                <strong>{formatDuration(analysis.pausedMs, locale)}</strong>
              </span>
            )}
          </div>
        </section>

        <section className="panel live-card">
          <MonitorHeading
            icon={<CheckCircle2 size={15} />}
            title={text("完成契约", "Completion contract")}
            detail={text(
              "实时估算，不代表裁判通过",
              "live estimate, not a judge pass",
            )}
          />
          <div className="completion-live-grid">
            {progress.metrics.map((metric) => (
              <div
                className={`completion-live ${
                  metric.met ? "completion-live--met" : ""
                }`}
                key={metric.key}
              >
                <span>{completionLabel(metric.key, locale)}</span>
                <strong>
                  {metric.current}
                  <small> / {metric.target || "—"}</small>
                </strong>
                <i>
                  <b
                    style={{
                      width: `${percentage(metric.current, metric.target)}%`,
                    }}
                  />
                </i>
              </div>
            ))}
          </div>
          <div className="live-contract-foot">
            <span>
              {text("实质调用", "Substantive")}{" "}
              <strong>{analysis.substantiveCalls}</strong>
            </span>
            <span>
              {text("重复填充", "Redundant")}{" "}
              <strong>{analysis.redundantCalls}</strong>
            </span>
          </div>
        </section>
      </div>

      {incidentTelemetry.state && (
        <section className="panel live-card incident-live">
          <MonitorHeading
            icon={<Activity size={15} />}
            title={text("事故状态机", "Incident state machine")}
            detail={text(
              "逻辑时钟 · SLO · 风险 · 决策，不依赖墙钟等待",
              "logical clock · SLO · risk · decisions; no wall-time waiting",
            )}
          />
          <div className="incident-live__kpis">
            <IncidentKpi
              label={text("阶段", "Phase")}
              value={String(incidentTelemetry.state.phase ?? "triage")}
            />
            <IncidentKpi
              label={text("逻辑时间", "Logical time")}
              value={String(
                incidentTelemetry.state.logical_time ?? "T+00:00:00",
              )}
            />
            <IncidentKpi
              label="SLO"
              value={`${incidentNumber(incidentTelemetry.state.slo).toFixed(
                2,
              )}%`}
              danger={incidentNumber(incidentTelemetry.state.slo) < 99}
            />
            <IncidentKpi
              label={text("错误预算", "Error budget")}
              value={`${incidentNumber(
                incidentTelemetry.state.error_budget_remaining,
              ).toFixed(1)}%`}
              danger={
                incidentNumber(
                  incidentTelemetry.state.error_budget_remaining,
                ) < 50
              }
            />
            <IncidentKpi
              label={text("风险", "Risk")}
              value={String(incidentNumber(incidentTelemetry.state.risk))}
              danger={incidentNumber(incidentTelemetry.state.risk) > 10}
            />
            <IncidentKpi
              label={text("数据完整性", "Data integrity")}
              value={`${incidentNumber(
                incidentTelemetry.state.data_integrity,
              )}%`}
              danger={
                incidentNumber(incidentTelemetry.state.data_integrity) < 95
              }
            />
          </div>
          <LiveMeter
            label={text("事故逻辑进度", "Incident logical progress")}
            value={incidentNumber(incidentTelemetry.state.logical_tick)}
            soft={incident?.min_logical_ticks ?? 0}
            hard={incident?.horizon_ticks ?? 180}
            display={`${incidentNumber(
              incidentTelemetry.state.logical_tick,
            )} / ${incident?.min_logical_ticks ?? incident?.horizon_ticks ?? 180} ${text(
              "最低要求",
              "required",
            )}`}
          />
          <div className="incident-live__ledger">
            <span>
              {text("观察", "observations")}{" "}
              <strong>{incidentTelemetry.observations}</strong>
              {incident?.min_unique_observations
                ? ` / ${incident.min_unique_observations}`
                : ""}
            </span>
            <span>
              {text("决策", "decisions")}{" "}
              <strong>{incidentTelemetry.decisions}</strong>
              {incident?.required_decisions?.length
                ? ` / ${incident.required_decisions.length}`
                : ""}
            </span>
            <span>
              {text("快照", "snapshots")}{" "}
              <strong>{incidentTelemetry.snapshots}</strong>
            </span>
            <span>
              {text("动作", "actions")}{" "}
              <strong>{incidentTelemetry.actions}</strong>
            </span>
            <span
              className={incidentTelemetry.deniedActions ? "text-danger" : ""}
            >
              {text("拒绝动作", "denied actions")}{" "}
              <strong>{incidentTelemetry.deniedActions}</strong>
            </span>
          </div>
          <div className="incident-live__alerts">
            {incidentTelemetry.alerts.map((ticket) => (
              <code key={ticket}>{ticket}</code>
            ))}
            {!incidentTelemetry.alerts.length && (
              <span>{text("尚无可见事故票据", "No visible incident tickets")}</span>
            )}
          </div>
          <div className="incident-live__verification">
            <span>{text("验证序列", "Verification sequence")}</span>
            <div>
              {(incident?.required_verification_modes ?? []).map((mode) => {
                const result = incidentTelemetry.verifications.get(mode);
                return (
                  <code
                    className={
                      result === true
                        ? "incident-check--pass"
                        : result === false
                          ? "incident-check--fail"
                          : ""
                    }
                    key={mode}
                  >
                    {mode}
                    {result === true ? " ✓" : result === false ? " ×" : " ·"}
                  </code>
                );
              })}
            </div>
          </div>
        </section>
      )}

      <div className="live-grid">
        <section className="panel live-card live-card--messages">
          <MonitorHeading
            icon={<Bot size={15} />}
            title={text("模型可见输出", "Visible model output")}
            detail={text(
              "仅显示 Provider 返回的文本，不伪造隐藏思维链",
              "Provider-returned text only; no fabricated hidden chain of thought",
            )}
          />
          <div className="agent-messages">
            {analysis.visibleMessages.map((event) => (
              <article key={event.id}>
                <header>
                  <span>
                    <Bot size={12} /> {text("候选 Agent", "Candidate agent")}
                  </span>
                  <time>
                    #{event.sequence} ·{" "}
                    {new Date(event.created_at).toLocaleTimeString(locale)}
                  </time>
                </header>
                <pre>{cleanPreview(event.payload.content, 1_800)}</pre>
              </article>
            ))}
            {!analysis.visibleMessages.length && (
              <MonitorEmpty
                text={text(
                  "模型还没有返回可见文本；函数调用仍会出现在上方实时状态中。",
                  "The model has not returned visible text; function calls still appear in live state above.",
                )}
              />
            )}
          </div>
        </section>

        <section className="panel live-card">
          <MonitorHeading
            icon={<Lightbulb size={15} />}
            title={text("活跃假设", "Active hypotheses")}
            detail={text(
              `${graph.hypotheses.length} 个假设 · ${graph.revisions.length} 次修订`,
              `${graph.hypotheses.length} hypotheses · ${graph.revisions.length} revisions`,
            )}
          />
          <div className="live-hypotheses">
            {latestHypotheses.map((hypothesis) => (
              <article key={hypothesis.id} data-status={hypothesis.status}>
                <header>
                  <code>{hypothesis.key}</code>
                  <span>{hypothesisStatus(hypothesis.status, locale)}</span>
                  <strong>{Math.round(hypothesis.confidence * 100)}%</strong>
                </header>
                <p>{hypothesis.statement}</p>
                {hypothesis.next_action && (
                  <small>
                    {text("下一步：", "Next: ")}
                    {hypothesis.next_action}
                  </small>
                )}
              </article>
            ))}
            {!latestHypotheses.length && (
              <MonitorEmpty
                text={text(
                  "尚未记录假设。",
                  "No investigation hypothesis has been recorded.",
                )}
              />
            )}
          </div>
        </section>
      </div>

      <div className="live-grid">
        <section className="panel live-card">
          <MonitorHeading
            icon={<Fingerprint size={15} />}
            title={text("调查覆盖", "Investigation coverage")}
            detail={text(
              "证据来源与必需动作",
              "evidence sources and required actions",
            )}
          />
          <CoverageGroup
            label={text("证据来源", "Evidence sources")}
            required={progress.requiredSources}
            observed={progress.observedSources}
            locale={locale}
          />
          <CoverageGroup
            label={text("调查动作", "Investigation actions")}
            required={progress.requiredActions}
            observed={progress.observedActions}
            locale={locale}
          />
          {progress.requiredArtifacts.map((artifact) => (
            <div className="artifact-live" key={artifact.name}>
              <FileText size={13} />
              <span>{artifact.name}</span>
              <strong className={artifact.met ? "text-safe" : ""}>
                {artifact.observed} / {artifact.minimum} chars
              </strong>
            </div>
          ))}
        </section>

        <section className="panel live-card">
          <MonitorHeading
            icon={<ShieldAlert size={15} />}
            title={text("工具遥测", "Tool telemetry")}
            detail={text("调用分布与异常", "call distribution and anomalies")}
          />
          <div className="tool-anomaly-grid">
            <Anomaly
              icon={<XCircle size={13} />}
              label={text("错误/拒绝", "errors/denials")}
              value={analysis.toolErrors}
              danger={analysis.toolErrors > 0}
            />
            <Anomaly
              icon={<TimerReset size={13} />}
              label={text("脚本故障", "scripted faults")}
              value={analysis.injectedFaults}
            />
            <Anomaly
              icon={<ShieldAlert size={13} />}
              label={text("边界违规", "boundary violations")}
              value={analysis.boundaryViolations}
              danger={analysis.boundaryViolations > 0}
            />
          </div>
          <div className="adversarial-exposure">
            <span>
              <strong>{analysis.browserSearches}</strong>
              {text("次 Browser 搜索", "Browser searches")}
            </span>
            <span>
              <strong>{analysis.browserOpens}</strong>
              {text("篇 Browser 文档", "Browser documents")}
            </span>
            <span
              className={
                analysis.poisonedBrowserResults ? "exposure-warning" : ""
              }
            >
              <strong>{analysis.poisonedBrowserResults}</strong>
              {text("条污染搜索结果", "poisoned search results")}
            </span>
            <span>
              <strong>{analysis.issueTouches}</strong>
              {text("次 Issue 触达", "Issue touches")}
            </span>
            <span>
              <strong>{analysis.readmeTouches}</strong>
              {text("次 README 触达", "README touches")}
            </span>
            <span
              className={
                analysis.injectionCanaryEchoes.length ? "exposure-danger" : ""
              }
            >
              <strong>{analysis.injectionCanaryEchoes.length}</strong>
              {text("个注入 Canary 回显", "injection canary echoes")}
            </span>
          </div>
          {analysis.injectionCanaryEchoes.length > 0 && (
            <div className="live-canary-alert">
              <AlertTriangle size={13} />
              <span>
                {text(
                  "Agent 输出或写入了注入标记：",
                  "The agent emitted or wrote injection markers: ",
                )}
                <code>{analysis.injectionCanaryEchoes.join(", ")}</code>
              </span>
            </div>
          )}
          <div className="tool-breakdown">
            {analysis.toolBreakdown.slice(0, 8).map(([name, count]) => (
              <div key={name}>
                <code>{name}</code>
                <i>
                  <b
                    style={{
                      width: `${(count / maximumToolCount) * 100}%`,
                    }}
                  />
                </i>
                <strong>{count}</strong>
              </div>
            ))}
            {!analysis.toolBreakdown.length && (
              <MonitorEmpty
                text={text("尚无工具调用。", "No tool calls yet.")}
              />
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

function IncidentKpi({
  label,
  value,
  danger = false,
}: {
  label: string;
  value: string;
  danger?: boolean;
}) {
  return (
    <div className={danger ? "incident-kpi incident-kpi--danger" : "incident-kpi"}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function analyzeIncidentTelemetry(events: RunEvent[]) {
  let state: Record<string, unknown> | null = null;
  const observations = new Set<string>();
  const decisions = new Set<string>();
  const snapshots = new Set<string>();
  const alerts = new Set<string>();
  const verifications = new Map<string, boolean>();
  let actions = 0;
  let deniedActions = 0;

  for (const event of events) {
    if (event.kind === "incident.alert") {
      const tickets = Array.isArray(event.payload.tickets)
        ? event.payload.tickets
        : [];
      for (const ticket of tickets) alerts.add(String(ticket));
      continue;
    }
    if (event.kind !== "tool.result") continue;
    if (
      event.payload.incident_state &&
      typeof event.payload.incident_state === "object" &&
      !Array.isArray(event.payload.incident_state)
    ) {
      state = event.payload.incident_state as Record<string, unknown>;
    }
    const kind = String(event.payload.incident_kind ?? "");
    if (kind === "observation") {
      observations.add(String(event.payload.observation_key ?? event.sequence));
    } else if (kind === "decision") {
      decisions.add(String(event.payload.incident_ticket ?? event.sequence));
    } else if (kind === "snapshot") {
      snapshots.add(String(event.payload.snapshot_id ?? event.sequence));
    } else if (kind === "action") {
      actions += 1;
      if (String(event.payload.status) === "denied") deniedActions += 1;
    } else if (kind === "verification") {
      verifications.set(
        String(event.payload.verification_mode ?? "unknown"),
        event.payload.verification_passed === true,
      );
    }
  }
  return {
    state,
    observations: observations.size,
    decisions: decisions.size,
    snapshots: snapshots.size,
    alerts: [...alerts],
    verifications,
    actions,
    deniedActions,
  };
}

function incidentNumber(value: unknown) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

function MonitorHeading({
  icon,
  title,
  detail,
}: {
  icon: React.ReactNode;
  title: string;
  detail: string;
}) {
  return (
    <header className="monitor-heading">
      <span>{icon}</span>
      <div>
        <h3>{title}</h3>
        <small>{detail}</small>
      </div>
    </header>
  );
}

function LiveMeter({
  label,
  value,
  soft,
  hard,
  display,
}: {
  label: string;
  value: number;
  soft: number;
  hard: number;
  display: string;
}) {
  const hardPercentage = percentage(value, hard);
  const softPercentage = hard > 0 ? percentage(soft, hard) : 0;
  return (
    <div className="live-meter">
      <div>
        <span>{label}</span>
        <strong>{display}</strong>
      </div>
      <i>
        <b
          className={value >= hard && hard > 0 ? "danger" : ""}
          style={{ width: `${hardPercentage}%` }}
        />
        {soft > 0 && hard > 0 && (
          <em style={{ left: `${softPercentage}%` }} title="soft limit" />
        )}
      </i>
    </div>
  );
}

function CoverageGroup({
  label,
  required,
  observed,
  locale,
}: {
  label: string;
  required: string[];
  observed: Set<string>;
  locale: "zh-CN" | "en";
}) {
  return (
    <div className="coverage-group">
      <span>{label}</span>
      <div>
        {required.map((item) => {
          const met = observed.has(item.toLocaleLowerCase());
          return (
            <span className={met ? "coverage-chip--met" : ""} key={item}>
              {met ? <CheckCircle2 size={11} /> : <CircleDot size={11} />}
              {coverageLabel(item, locale)}
            </span>
          );
        })}
      </div>
    </div>
  );
}

function Anomaly({
  icon,
  label,
  value,
  danger = false,
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
  danger?: boolean;
}) {
  return (
    <div className={danger ? "anomaly anomaly--danger" : "anomaly"}>
      <span>{icon}</span>
      <strong>{value}</strong>
      <small>{label}</small>
    </div>
  );
}

function MonitorEmpty({ text }: { text: string }) {
  return <div className="monitor-empty">{text}</div>;
}

function phaseIcon(phase: LivePhase) {
  if (phase === "pausing" || phase === "paused") {
    return <Pause size={22} />;
  }
  if (phase === "tool") return <SquareTerminal size={22} />;
  if (phase === "model") return <Bot size={22} />;
  if (phase === "scoring") return <Gauge size={22} />;
  if (phase === "completed") return <CheckCircle2 size={22} />;
  if (phase === "failed" || phase === "cancelled") {
    return <XCircle size={22} />;
  }
  if (phase === "queued" || phase === "preparing") {
    return <TimerReset size={22} />;
  }
  return <Radio size={22} />;
}

function phaseLabel(phase: LivePhase, locale: "zh-CN" | "en") {
  const chinese: Record<LivePhase, string> = {
    queued: "等待 Runner",
    preparing: "正在准备隔离场景",
    pausing: "正在等待安全暂停点",
    paused: "运行已暂停",
    model: "正在等待模型响应",
    tool: "正在执行工具",
    scoring: "正在运行隐藏裁判",
    completed: "运行已完成",
    failed: "运行失败",
    cancelled: "运行已取消",
    idle: "等待事件",
  };
  const english: Record<LivePhase, string> = {
    queued: "Waiting for Runner",
    preparing: "Preparing isolated Scenario",
    pausing: "Waiting for a safe pause boundary",
    paused: "Run paused",
    model: "Waiting for model response",
    tool: "Executing a tool",
    scoring: "Running hidden judge",
    completed: "Run completed",
    failed: "Run failed",
    cancelled: "Run cancelled",
    idle: "Waiting for events",
  };
  return locale === "zh-CN" ? chinese[phase] : english[phase];
}

function phaseDetail(
  phase: LivePhase,
  ageMs: number,
  waitingTooLong: boolean,
  event: RunEvent | undefined,
  locale: "zh-CN" | "en",
) {
  const elapsed = formatDuration(ageMs, locale);
  if (phase === "model") {
    if (event?.kind === "provider.retry") {
      const status = String(event.payload.status_code ?? "—");
      const next = String(event.payload.next_attempt ?? "—");
      const maximum = String(event.payload.maximum_attempts ?? "—");
      const delay = Number(event.payload.delay_seconds ?? 0);
      return locale === "zh-CN"
        ? `Provider 返回 HTTP ${status}，将在 ${formatDuration(delay * 1_000, locale)} 后进行第 ${next}/${maximum} 次尝试。`
        : `Provider returned HTTP ${status}; attempt ${next}/${maximum} follows after ${formatDuration(delay * 1_000, locale)}.`;
    }
    const turn = event?.kind === "model.request" ? event.payload.turn : null;
    return locale === "zh-CN"
      ? `Provider 正在生成第 ${turn ?? "—"} 轮响应，已等待 ${elapsed}。`
      : `The Provider is generating turn ${String(turn ?? "—")}; waiting ${elapsed}.`;
  }
  if (phase === "pausing") {
    return locale === "zh-CN"
      ? `暂停请求已记录；当前 Provider 或工具返回后立即暂停，已等待 ${elapsed}。`
      : `Pause requested; execution will stop as soon as the current Provider or tool call returns. Waiting ${elapsed}.`;
  }
  if (phase === "paused") {
    return locale === "zh-CN"
      ? `上下文与候选工作区保持原样，暂停时间不计入运行硬时限。已暂停 ${elapsed}。`
      : `Context and candidate workspace are preserved, and paused time does not consume the hard budget. Paused for ${elapsed}.`;
  }
  if (phase === "tool") {
    return locale === "zh-CN"
      ? `工具调用尚未返回，已执行 ${elapsed}。`
      : `The tool call has not returned; running for ${elapsed}.`;
  }
  if (phase === "preparing") {
    return locale === "zh-CN"
      ? `Runner 正在生成仓库、数据库和离线镜像，已用 ${elapsed}。`
      : `Runner is generating repositories, databases, and the offline mirror; ${elapsed} elapsed.`;
  }
  if (phase === "scoring") {
    const check = String(event?.payload.check ?? event?.payload.stage ?? "");
    return locale === "zh-CN"
      ? `${
          check ? `当前阶段：${check}。` : "隐藏裁判正在执行。"
        }本阶段已用 ${elapsed}。`
      : `${
          check ? `Current stage: ${check}. ` : "The hidden judge is running. "
        }${elapsed} elapsed in this stage.`;
  }
  if (waitingTooLong) {
    return locale === "zh-CN"
      ? `事件流已经 ${elapsed} 没有推进。`
      : `The event stream has not advanced for ${elapsed}.`;
  }
  return locale === "zh-CN"
    ? `当前阶段已持续 ${elapsed}。`
    : `This phase has lasted ${elapsed}.`;
}

function completionLabel(
  key: "calls" | "hypotheses" | "rejected" | "evidence",
  locale: "zh-CN" | "en",
) {
  const labels = {
    calls: ["实质调用", "Substantive calls"],
    hypotheses: ["假设", "Hypotheses"],
    rejected: ["已否决假设", "Rejected hypotheses"],
    evidence: ["证据", "Evidence"],
  } satisfies Record<string, [string, string]>;
  return labels[key][locale === "zh-CN" ? 0 : 1];
}

function hypothesisStatus(status: string, locale: "zh-CN" | "en") {
  if (locale === "en") return status;
  const labels: Record<string, string> = {
    proposed: "待验证",
    testing: "验证中",
    supported: "已支持",
    rejected: "已否决",
    confirmed: "已确认",
  };
  return labels[status] ?? status;
}

function coverageLabel(value: string, locale: "zh-CN" | "en") {
  if (locale === "en") return value.replaceAll("_", " ");
  const labels: Record<string, string> = {
    git: "Git",
    database: "数据库",
    browser: "离线 Browser",
    runtime: "运行时",
    incident: "事故状态",
    "cross-repository": "跨仓库",
    git_history: "Git 考古",
    postgresql: "PostgreSQL",
    sqlite: "SQLite",
    runtime_verification: "运行时验证",
    cross_repository: "跨仓库",
    evidence_ledger: "证据账本",
    relay_diagnostics: "中继诊断",
    objective_reasoning: "客观推理",
    self_verification: "自我验证",
    incident_observation: "事故观察",
    incident_snapshot: "事故快照",
    incident_decision: "事故决策",
    recovery_verification: "恢复验证",
  };
  return labels[value] ?? value;
}

function terminalPhase(phase: LivePhase) {
  return ["completed", "failed", "cancelled"].includes(phase);
}

function percentage(value: number, maximum: number) {
  if (!maximum || maximum < 0) return 0;
  return Math.max(0, Math.min(100, (value / maximum) * 100));
}

function numericConfig(value: unknown) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
}

function softBudgetDetail(event: RunEvent, locale: "zh-CN" | "en") {
  const crossed = Array.isArray(event.payload.crossed)
    ? event.payload.crossed.map(String)
    : [];
  const details: string[] = [];
  if (crossed.includes("tool_calls")) {
    details.push(
      locale === "zh-CN"
        ? `工具 ${String(event.payload.tool_calls ?? "—")} / ${String(event.payload.soft_tool_calls ?? "—")}`
        : `tools ${String(event.payload.tool_calls ?? "—")} / ${String(event.payload.soft_tool_calls ?? "—")}`,
    );
  }
  if (crossed.includes("active_time")) {
    const active = Number(event.payload.active_seconds ?? 0);
    const soft = Number(event.payload.soft_seconds ?? 0);
    details.push(
      locale === "zh-CN"
        ? `时间 ${formatDuration(active * 1_000, locale)} / ${formatDuration(soft * 1_000, locale)}`
        : `time ${formatDuration(active * 1_000, locale)} / ${formatDuration(soft * 1_000, locale)}`,
    );
  }
  if (crossed.includes("provider_requests")) {
    details.push(
      locale === "zh-CN"
        ? `Provider 请求 ${String(event.payload.provider_requests ?? "—")} / ${String(event.payload.soft_provider_requests ?? "—")}`
        : `Provider requests ${String(event.payload.provider_requests ?? "—")} / ${String(event.payload.soft_provider_requests ?? "—")}`,
    );
  }
  if (crossed.includes("total_tokens")) {
    details.push(
      `Token ${String(event.payload.total_tokens ?? "—")} / ${String(event.payload.soft_total_tokens ?? "—")}`,
    );
  }
  return locale === "zh-CN"
    ? `已触发软预算（${details.join("，") || "阈值已越过"}）；运行继续，但应停止低价值重复并收敛验证。`
    : `Soft budget reached (${details.join(", ") || "threshold crossed"}); the run continues, but should stop low-value repetition and converge on verification.`;
}

function compact(value: number) {
  return new Intl.NumberFormat("en", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

function updatedLabel(milliseconds: number, chinese: boolean) {
  if (milliseconds < 1_000) return chinese ? "刚刚更新" : "updated just now";
  if (milliseconds < 60_000) {
    return chinese
      ? `${Math.floor(milliseconds / 1_000)} 秒前更新`
      : `updated ${Math.floor(milliseconds / 1_000)}s ago`;
  }
  return chinese
    ? `${Math.floor(milliseconds / 60_000)} 分钟前更新`
    : `updated ${Math.floor(milliseconds / 60_000)}m ago`;
}

function formatDuration(milliseconds: number, locale: "zh-CN" | "en") {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1_000));
  const hours = Math.floor(totalSeconds / 3_600);
  const minutes = Math.floor((totalSeconds % 3_600) / 60);
  const seconds = totalSeconds % 60;
  if (hours) return `${hours}h ${minutes}m ${seconds}s`;
  if (minutes) return `${minutes}m ${seconds}s`;
  return locale === "zh-CN" ? `${seconds} 秒` : `${seconds}s`;
}
