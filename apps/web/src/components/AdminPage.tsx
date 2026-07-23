import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  Bot,
  Cpu,
  Database,
  HardDrive,
  MemoryStick,
  Plus,
  RefreshCw,
  Server,
  ShieldCheck,
  UserCog,
  Users,
} from "lucide-react";
import { type FormEvent, useState } from "react";
import { api } from "../lib/api";
import { useLocale } from "../lib/i18n";
import type { ServerMonitor, UserAccount, UserRole } from "../lib/types";

export default function AdminPage({
  currentUser,
}: {
  currentUser: UserAccount;
}) {
  const { locale, text } = useLocale();
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [error, setError] = useState("");
  const summary = useQuery({
    queryKey: ["admin-summary"],
    queryFn: api.adminSummary,
  });
  const users = useQuery({
    queryKey: ["admin-users"],
    queryFn: api.adminUsers,
  });
  const settings = useQuery({
    queryKey: ["platform-settings"],
    queryFn: api.platformSettings,
  });
  const monitor = useQuery({
    queryKey: ["server-monitor"],
    queryFn: api.serverMonitor,
    refetchInterval: 5_000,
  });
  const updateSettings = useMutation({
    mutationFn: api.updatePlatformSettings,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["platform-settings"] });
      void queryClient.invalidateQueries({ queryKey: ["auth-config"] });
    },
  });
  const create = useMutation({
    mutationFn: api.createUser,
    onSuccess: () => {
      setShowCreate(false);
      setError("");
      void refreshAdmin(queryClient);
    },
    onError: (cause) =>
      setError(cause instanceof Error ? cause.message : String(cause)),
  });
  const update = useMutation({
    mutationFn: ({
      id,
      payload,
    }: {
      id: string;
      payload: Record<string, unknown>;
    }) => api.updateUser(id, payload),
    onSuccess: () => void refreshAdmin(queryClient),
    onError: (cause) =>
      setError(cause instanceof Error ? cause.message : String(cause)),
  });
  const revoke = useMutation({
    mutationFn: api.revokeUserSessions,
    onSuccess: () => setError(""),
    onError: (cause) =>
      setError(cause instanceof Error ? cause.message : String(cause)),
  });
  const submitUser = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    create.mutate({
      username: data.get("username"),
      password: data.get("password"),
      role: data.get("role"),
      enabled: true,
    });
  };

  return (
    <>
      <div className="page-header">
        <div>
          <span className="eyebrow">
            {text("管理员后台", "ADMINISTRATION")}
          </span>
          <h1>{text("用户、策略与服务器。", "Users, policy, and server.")}</h1>
          <p>
            {text(
              "管理平台访问权限，并监控控制平面与隔离 Runner 的健康状态。",
              "Manage platform access and monitor the control plane and isolated Runner.",
            )}
          </p>
        </div>
        <button
          className="button"
          onClick={() => setShowCreate((value) => !value)}
        >
          <Plus size={15} /> {text("创建账户", "Create account")}
        </button>
      </div>
      <div className="stat-grid">
        <AdminStat
          icon={<Users />}
          label={text("账户", "Accounts")}
          value={summary.data?.users}
        />
        <AdminStat
          icon={<ShieldCheck />}
          label={text("管理员", "Administrators")}
          value={summary.data?.admins}
        />
        <AdminStat
          icon={<Bot />}
          label={text("模型配置", "Model profiles")}
          value={summary.data?.models}
        />
        <AdminStat
          icon={<Activity />}
          label={text("活跃运行", "Active runs")}
          value={summary.data?.active_runs}
        />
      </div>
      <div className="admin-grid">
        <section className="panel">
          <PanelTitle
            icon={<UserCog size={16} />}
            title={text("注册策略", "Registration policy")}
          />
          <div className="registration-switch">
            <div>
              <strong>
                {text("允许公开注册", "Allow public registration")}
              </strong>
              <span>
                {text(
                  "关闭后仍可由管理员创建账户。",
                  "Administrators can still create accounts while disabled.",
                )}
              </span>
            </div>
            <button
              className={`switch ${settings.data?.registration_enabled ? "switch--on" : ""}`}
              type="button"
              aria-pressed={Boolean(settings.data?.registration_enabled)}
              onClick={() =>
                updateSettings.mutate({
                  registration_enabled: !settings.data?.registration_enabled,
                })
              }
            >
              <i />
              {settings.data?.registration_enabled
                ? text("已开放", "Open")
                : text("已关闭", "Closed")}
            </button>
          </div>
        </section>
        <section className="panel">
          <PanelTitle
            icon={<Server size={16} />}
            title={text("服务状态", "Service status")}
          />
          <div className="service-health">
            <HealthRow label="API" good={Boolean(monitor.data?.api.healthy)} />
            <HealthRow
              label="Runner"
              good={Boolean(monitor.data?.runner.healthy)}
            />
            <HealthRow
              label="Rootless Docker"
              good={Boolean(monitor.data?.runner.docker_ready)}
            />
            <HealthRow
              label="PostgreSQL"
              good={Boolean(monitor.data?.database.healthy)}
            />
          </div>
        </section>
      </div>
      {showCreate && (
        <section className="panel admin-create">
          <PanelTitle
            icon={<Plus size={16} />}
            title={text("新账户", "New account")}
          />
          <form className="form-grid" onSubmit={submitUser}>
            <label className="field">
              <span>{text("账户名", "Account name")}</span>
              <input
                name="username"
                minLength={2}
                maxLength={32}
                autoComplete="username"
                required
              />
            </label>
            <label className="field">
              <span>{text("初始密码", "Initial password")}</span>
              <input name="password" type="password" minLength={8} required />
            </label>
            <label className="field">
              <span>{text("角色", "Role")}</span>
              <select name="role" defaultValue="user">
                <option value="user">user</option>
                <option value="admin">admin</option>
              </select>
            </label>
            <button className="button" disabled={create.isPending}>
              <Plus size={14} /> {text("创建", "Create")}
            </button>
          </form>
        </section>
      )}
      {error && <div className="callout callout--danger">{error}</div>}
      <section className="panel">
        <PanelTitle
          icon={<Users size={16} />}
          title={text("用户管理", "User management")}
        />
        <div className="table-scroll">
          <table className="data-table admin-users">
            <thead>
              <tr>
                <th>{text("用户", "User")}</th>
                <th>{text("角色", "Role")}</th>
                <th>{text("状态", "Status")}</th>
                <th>{text("最近登录", "Last login")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {(users.data ?? []).map((user) => (
                <tr key={user.id}>
                  <td>
                    <strong>{user.username}</strong>
                  </td>
                  <td>
                    <select
                      value={user.role}
                      disabled={user.id === currentUser.id}
                      onChange={(event) =>
                        update.mutate({
                          id: user.id,
                          payload: { role: event.target.value as UserRole },
                        })
                      }
                    >
                      <option value="user">user</option>
                      <option value="admin">admin</option>
                    </select>
                  </td>
                  <td>
                    <button
                      className={`pill ${user.enabled ? "pill--lime" : ""}`}
                      disabled={user.id === currentUser.id}
                      onClick={() =>
                        update.mutate({
                          id: user.id,
                          payload: { enabled: !user.enabled },
                        })
                      }
                    >
                      {user.enabled
                        ? text("已启用", "enabled")
                        : text("已停用", "disabled")}
                    </button>
                  </td>
                  <td>
                    {user.last_login_at
                      ? new Date(user.last_login_at).toLocaleString(locale)
                      : "—"}
                  </td>
                  <td>
                    <button
                      className="button button--ghost button--small"
                      onClick={() => revoke.mutate(user.id)}
                    >
                      {text("撤销会话", "Revoke sessions")}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <ServerPanel monitor={monitor.data} text={text} />
    </>
  );
}

function ServerPanel({
  monitor,
  text,
}: {
  monitor?: ServerMonitor;
  text: (chinese: string, english: string) => string;
}) {
  const api = monitor?.api;
  const runner = monitor?.runner;
  const memoryTotal = Number(api?.memory_total ?? 0);
  const memoryUsed = Number(api?.memory_used ?? 0);
  const diskTotal = Number(api?.disk_total ?? 0);
  const diskUsed = Number(api?.disk_used ?? 0);
  return (
    <section className="panel">
      <div className="panel-heading">
        <div className="panel-heading__icon">
          <Server size={16} />
        </div>
        <div>
          <h3>{text("服务器监控", "Server monitoring")}</h3>
          <span>
            {text(
              "每 5 秒刷新 · 安全聚合指标",
              "Refreshes every 5 seconds · safe aggregate metrics",
            )}
          </span>
        </div>
        <RefreshCw className="monitor-refresh" size={15} />
      </div>
      <div className="monitor-grid">
        <MonitorMetric
          icon={<Cpu />}
          label={text("CPU Load", "CPU load")}
          value={`${Number(api?.load_1 ?? 0).toFixed(2)} / ${api?.cpu_count ?? "—"}`}
          ratio={
            Number(api?.load_1 ?? 0) / Math.max(1, Number(api?.cpu_count ?? 1))
          }
        />
        <MonitorMetric
          icon={<MemoryStick />}
          label={text("内存", "Memory")}
          value={`${formatBytes(memoryUsed)} / ${formatBytes(memoryTotal)}`}
          ratio={memoryTotal ? memoryUsed / memoryTotal : 0}
        />
        <MonitorMetric
          icon={<HardDrive />}
          label={text("磁盘", "Disk")}
          value={`${formatBytes(diskUsed)} / ${formatBytes(diskTotal)}`}
          ratio={diskTotal ? diskUsed / diskTotal : 0}
        />
        <MonitorMetric
          icon={<Database />}
          label="PostgreSQL"
          value={`${monitor?.database.latency_ms ?? "—"} ms`}
          ratio={Math.min(1, Number(monitor?.database.latency_ms ?? 0) / 500)}
        />
      </div>
      <div className="docker-metrics">
        <span>Docker {runner?.docker_version ?? "—"}</span>
        <span>
          {text("运行中容器", "Running containers")}:{" "}
          {runner?.containers_running ?? "—"}
        </span>
        <span>
          {text("镜像", "Images")}: {runner?.images ?? "—"}
        </span>
        <span>
          {text("排队", "Queued")}: {monitor?.queue.queued ?? "—"}
        </span>
        <span>
          {text("处理中", "Active")}: {monitor?.queue.active ?? "—"}
        </span>
      </div>
    </section>
  );
}

function AdminStat({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value?: number;
}) {
  return (
    <article className="stat-card">
      <div className="stat-card__icon">{icon}</div>
      <span>{label}</span>
      <strong>{value ?? "—"}</strong>
      <small>platform</small>
    </article>
  );
}

function PanelTitle({ icon, title }: { icon: React.ReactNode; title: string }) {
  return (
    <div className="panel-heading">
      <div className="panel-heading__icon">{icon}</div>
      <div>
        <h3>{title}</h3>
      </div>
    </div>
  );
}

function HealthRow({ label, good }: { label: string; good: boolean }) {
  return (
    <div>
      <span>
        <i
          className={`status-dot ${good ? "status-dot--safe" : "status-dot--danger"}`}
        />
        {label}
      </span>
      <strong className={good ? "text-safe" : "text-danger"}>
        {good ? "online" : "offline"}
      </strong>
    </div>
  );
}

function MonitorMetric({
  icon,
  label,
  value,
  ratio,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  ratio: number;
}) {
  const width = `${Math.max(0, Math.min(100, ratio * 100))}%`;
  return (
    <div className="monitor-metric">
      <span>
        {icon}
        {label}
      </span>
      <strong>{value}</strong>
      <div>
        <i style={{ width }} />
      </div>
    </div>
  );
}

function formatBytes(value: number) {
  if (!value) return "—";
  const gib = value / 1024 / 1024 / 1024;
  return `${gib.toFixed(gib >= 10 ? 0 : 1)} GiB`;
}

function refreshAdmin(queryClient: ReturnType<typeof useQueryClient>) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: ["admin-users"] }),
    queryClient.invalidateQueries({ queryKey: ["admin-summary"] }),
  ]);
}
