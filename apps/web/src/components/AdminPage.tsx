import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  Bot,
  CheckCircle2,
  Clock3,
  Cpu,
  Database,
  Gauge,
  HardDrive,
  KeyRound,
  MemoryStick,
  Plus,
  RefreshCw,
  Search,
  Server,
  ShieldCheck,
  UserCog,
  UserRound,
  Users,
  X,
} from "lucide-react";
import { type FormEvent, useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import { useLocale } from "../lib/i18n";
import type { ServerMonitor, UserAccount, UserRole } from "../lib/types";

type TextFn = (chinese: string, english: string) => string;

type AccountAction =
  | {
      kind: "role";
      user: UserAccount;
      nextRole: UserRole;
    }
  | {
      kind: "status";
      user: UserAccount;
      nextEnabled: boolean;
    }
  | {
      kind: "sessions";
      user: UserAccount;
    };

type Notice = {
  tone: "success" | "danger";
  message: string;
};

export default function AdminPage({
  currentUser,
}: {
  currentUser: UserAccount;
}) {
  const { locale, text } = useLocale();
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [confirmAction, setConfirmAction] = useState<AccountAction | null>(
    null,
  );
  const [runnerConcurrency, setRunnerConcurrency] = useState(2);
  const [userSearch, setUserSearch] = useState("");

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

  useEffect(() => {
    if (settings.data) {
      setRunnerConcurrency(settings.data.runner_concurrency);
    }
  }, [settings.data]);

  const updateSettings = useMutation({
    mutationFn: api.updatePlatformSettings,
    onSuccess: (updated, variables) => {
      setRunnerConcurrency(updated.runner_concurrency);
      setNotice({
        tone: "success",
        message:
          "registration_enabled" in variables
            ? variables.registration_enabled
              ? text("公开注册已开放。", "Public registration is now open.")
              : text("公开注册已关闭。", "Public registration is now closed.")
            : text(
                `Runner 并发数已更新为 ${updated.runner_concurrency}。`,
                `Runner concurrency updated to ${updated.runner_concurrency}.`,
              ),
      });
      void queryClient.invalidateQueries({ queryKey: ["platform-settings"] });
      void queryClient.invalidateQueries({ queryKey: ["auth-config"] });
    },
    onError: (cause) => setFailure(cause, setNotice),
  });

  const create = useMutation({
    mutationFn: api.createUser,
    onSuccess: (created) => {
      setShowCreate(false);
      setNotice({
        tone: "success",
        message: text(
          `账户 ${created.username} 已创建。`,
          `Account ${created.username} was created.`,
        ),
      });
      void refreshAdmin(queryClient);
    },
    onError: (cause) => setFailure(cause, setNotice),
  });

  const update = useMutation({
    mutationFn: ({
      id,
      payload,
    }: {
      id: string;
      payload: Record<string, unknown>;
    }) => api.updateUser(id, payload),
    onSuccess: (updated) => {
      setConfirmAction(null);
      setNotice({
        tone: "success",
        message: text(
          `账户 ${updated.username} 已更新。`,
          `Account ${updated.username} was updated.`,
        ),
      });
      void refreshAdmin(queryClient);
    },
    onError: (cause) => setFailure(cause, setNotice),
  });

  const revoke = useMutation({
    mutationFn: api.revokeUserSessions,
    onSuccess: (_, userId) => {
      const target = users.data?.find((user) => user.id === userId);
      setConfirmAction(null);
      setNotice({
        tone: "success",
        message: text(
          `${target?.username ?? "该账户"}的其他会话已撤销。`,
          `Other sessions for ${target?.username ?? "the account"} were revoked.`,
        ),
      });
    },
    onError: (cause) => setFailure(cause, setNotice),
  });

  const filteredUsers = useMemo(() => {
    const normalized = userSearch.trim().toLocaleLowerCase(locale);
    if (!normalized) return users.data ?? [];
    return (users.data ?? []).filter(
      (user) =>
        user.username.toLocaleLowerCase(locale).includes(normalized) ||
        user.role.includes(normalized),
    );
  }, [locale, userSearch, users.data]);

  const serviceStates = [
    monitor.data?.api.healthy,
    monitor.data?.runner.healthy,
    monitor.data?.runner.docker_ready,
    monitor.data?.database.healthy,
  ];
  const monitorReady = Boolean(monitor.data);
  const allServicesHealthy =
    monitorReady && serviceStates.every((state) => Boolean(state));

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

  const runAccountAction = () => {
    if (!confirmAction) return;
    if (confirmAction.kind === "sessions") {
      revoke.mutate(confirmAction.user.id);
      return;
    }
    update.mutate({
      id: confirmAction.user.id,
      payload:
        confirmAction.kind === "role"
          ? { role: confirmAction.nextRole }
          : { enabled: confirmAction.nextEnabled },
    });
  };

  const refreshControlPlane = () => {
    void Promise.all([
      summary.refetch(),
      users.refetch(),
      settings.refetch(),
      monitor.refetch(),
    ]);
  };

  const loading =
    summary.isLoading ||
    users.isLoading ||
    settings.isLoading ||
    monitor.isLoading;
  const hasQueryError =
    summary.isError || users.isError || settings.isError || monitor.isError;

  return (
    <>
      <header className="admin-hero">
        <div className="admin-hero__copy">
          <span className="eyebrow">
            {text("控制平面 / 管理员", "CONTROL PLANE / ADMIN")}
          </span>
          <h1>{text("平台控制中心", "Platform control center")}</h1>
          <p>
            {text(
              "统一管理访问策略、账户权限、Runner 容量与服务器健康状态。",
              "Manage access policy, account privileges, Runner capacity, and server health from one place.",
            )}
          </p>
        </div>
        <div className="admin-hero__status">
          <div
            className={`admin-health-beacon ${
              !monitorReady
                ? "admin-health-beacon--unknown"
                : allServicesHealthy
                  ? "admin-health-beacon--safe"
                  : "admin-health-beacon--danger"
            }`}
          >
            {allServicesHealthy ? (
              <CheckCircle2 size={18} />
            ) : (
              <Activity size={18} />
            )}
            <div>
              <span>{text("控制平面状态", "Control plane status")}</span>
              <strong>
                {!monitorReady
                  ? text("正在采样", "Sampling")
                  : allServicesHealthy
                    ? text("全部服务正常", "All systems operational")
                    : text("需要关注", "Attention required")}
              </strong>
            </div>
          </div>
          <div className="admin-hero__actions">
            <button
              className="button button--ghost"
              type="button"
              disabled={loading}
              onClick={refreshControlPlane}
            >
              <RefreshCw
                className={loading ? "spin" : undefined}
                size={14}
              />
              {text("刷新", "Refresh")}
            </button>
            <button
              className="button"
              type="button"
              onClick={() => {
                setNotice(null);
                setShowCreate(true);
              }}
            >
              <Plus size={15} /> {text("创建账户", "Create account")}
            </button>
          </div>
        </div>
      </header>

      {notice && (
        <div
          className={`admin-notice admin-notice--${notice.tone}`}
          role={notice.tone === "danger" ? "alert" : "status"}
        >
          {notice.tone === "success" ? (
            <CheckCircle2 size={16} />
          ) : (
            <AlertTriangle size={16} />
          )}
          <span>{notice.message}</span>
          <button
            type="button"
            aria-label={text("关闭通知", "Dismiss notification")}
            onClick={() => setNotice(null)}
          >
            <X size={14} />
          </button>
        </div>
      )}
      {hasQueryError && !notice && (
        <div className="admin-notice admin-notice--danger" role="alert">
          <AlertTriangle size={16} />
          <span>
            {text(
              "部分控制平面数据加载失败；已显示的监控数据可能已过期。",
              "Some control-plane data failed to load; visible telemetry may be stale.",
            )}
          </span>
          <button
            type="button"
            aria-label={text("重新加载", "Reload")}
            onClick={refreshControlPlane}
          >
            <RefreshCw size={14} />
          </button>
        </div>
      )}

      <div className="stat-grid admin-stat-grid">
        <AdminStat
          icon={<Users />}
          label={text("账户", "Accounts")}
          value={summary.data?.users}
          detail={text(
            `${summary.data?.enabled_users ?? "—"} 个已启用`,
            `${summary.data?.enabled_users ?? "—"} enabled`,
          )}
        />
        <AdminStat
          icon={<Bot />}
          label={text("模型配置", "Model profiles")}
          value={summary.data?.models}
          detail={text("平台可见配置", "available profiles")}
        />
        <AdminStat
          icon={<Activity />}
          label={text("累计运行", "Total runs")}
          value={summary.data?.total_runs}
          detail={text("未归档记录", "unarchived records")}
        />
        <AdminStat
          accent={Boolean(summary.data?.active_runs)}
          icon={<Gauge />}
          label={text("活动队列", "Active queue")}
          value={summary.data?.active_runs}
          detail={text(
            `${monitor.data?.queue.queued ?? "—"} 个等待中`,
            `${monitor.data?.queue.queued ?? "—"} queued`,
          )}
        />
      </div>

      <div className="admin-control-grid">
        <section className="panel admin-control-card">
          <PanelTitle
            icon={<UserCog size={16} />}
            title={text("注册策略", "Registration policy")}
            subtitle={text("控制新用户入口", "Control new account access")}
          />
          <div className="admin-policy">
            <div className="admin-policy__copy">
              <strong>{text("允许公开注册", "Public registration")}</strong>
              <span>
                {text(
                  "关闭后注册入口立即消失，管理员仍可手动创建账户。",
                  "When disabled, the sign-up entry disappears immediately. Administrators can still provision accounts.",
                )}
              </span>
            </div>
            <button
              className={`admin-switch ${
                settings.data?.registration_enabled
                  ? "admin-switch--on"
                  : ""
              }`}
              type="button"
              disabled={settings.isLoading || updateSettings.isPending}
              aria-pressed={Boolean(settings.data?.registration_enabled)}
              onClick={() =>
                updateSettings.mutate({
                  registration_enabled:
                    !settings.data?.registration_enabled,
                })
              }
            >
              <i />
              <span>
                {settings.data?.registration_enabled
                  ? text("开放", "Open")
                  : text("关闭", "Closed")}
              </span>
            </button>
          </div>
          <div className="admin-policy__footer">
            <ShieldCheck size={13} />
            <span>
              {text(
                `管理员账户 ${summary.data?.admins ?? "—"} 个`,
                `${summary.data?.admins ?? "—"} administrator accounts`,
              )}
            </span>
          </div>
        </section>

        <section className="panel admin-control-card">
          <PanelTitle
            icon={<Gauge size={16} />}
            title={text("运行并发", "Run concurrency")}
            subtitle={text("限制 Runner 同时领取任务", "Limit simultaneous claims")}
          />
          <div className="concurrency-setting">
            <div className="concurrency-setting__summary">
              <div>
                <strong>{runnerConcurrency}</strong>
                <span>{text("并发槽位", "run slots")}</span>
              </div>
              <span>
                {text(
                  "降低数值不会中断正在运行的测试。",
                  "Lowering the limit never interrupts active runs.",
                )}
              </span>
            </div>
            <input
              className="concurrency-setting__range"
              type="range"
              min={1}
              max={16}
              step={1}
              value={runnerConcurrency}
              aria-label={text("Runner 并发槽位", "Runner execution slots")}
              onChange={(event) =>
                setRunnerConcurrency(Number(event.target.value))
              }
            />
            <div className="concurrency-setting__control">
              <span>01</span>
              <input
                type="number"
                min={1}
                max={16}
                value={runnerConcurrency}
                aria-label={text(
                  "Runner 并发槽位数值",
                  "Runner execution slot value",
                )}
                onChange={(event) =>
                  setRunnerConcurrency(
                    Math.max(1, Math.min(16, Number(event.target.value) || 1)),
                  )
                }
              />
              <span>16</span>
              <button
                className="button button--small"
                type="button"
                disabled={
                  settings.isLoading ||
                  updateSettings.isPending ||
                  runnerConcurrency === settings.data?.runner_concurrency
                }
                onClick={() =>
                  updateSettings.mutate({
                    runner_concurrency: runnerConcurrency,
                  })
                }
              >
                {updateSettings.isPending
                  ? text("保存中…", "Saving…")
                  : text("应用", "Apply")}
              </button>
            </div>
          </div>
        </section>

        <section className="panel admin-control-card">
          <PanelTitle
            icon={<Server size={16} />}
            title={text("服务状态", "Service status")}
            subtitle={
              monitor.data?.observed_at
                ? text(
                    `采样于 ${formatDate(monitor.data.observed_at, locale, true)}`,
                    `Sampled ${formatDate(monitor.data.observed_at, locale, true)}`,
                  )
                : text("等待首次采样", "Awaiting first sample")
            }
          />
          <div className="service-health">
            <HealthRow
              label="API"
              state={healthState(monitorReady, monitor.data?.api.healthy)}
              text={text}
            />
            <HealthRow
              label="Runner"
              state={healthState(monitorReady, monitor.data?.runner.healthy)}
              text={text}
            />
            <HealthRow
              label="Rootless Docker"
              state={healthState(
                monitorReady,
                monitor.data?.runner.docker_ready,
              )}
              text={text}
            />
            <HealthRow
              label="PostgreSQL"
              state={healthState(
                monitorReady,
                monitor.data?.database.healthy,
              )}
              text={text}
            />
          </div>
        </section>
      </div>

      <section className="panel admin-users-panel">
        <div className="panel-heading admin-users-heading">
          <div className="panel-heading__icon">
            <Users size={16} />
          </div>
          <div>
            <h3>{text("用户与权限", "Users and permissions")}</h3>
            <span>
              {text(
                `${users.data?.length ?? 0} 个账户 · 修改高权限操作前会要求确认`,
                `${users.data?.length ?? 0} accounts · privileged changes require confirmation`,
              )}
            </span>
          </div>
          <label className="admin-user-search">
            <Search size={13} />
            <input
              value={userSearch}
              placeholder={text("搜索账户或角色", "Search user or role")}
              aria-label={text("搜索账户或角色", "Search user or role")}
              onChange={(event) => setUserSearch(event.target.value)}
            />
            {userSearch && (
              <button
                type="button"
                aria-label={text("清除搜索", "Clear search")}
                onClick={() => setUserSearch("")}
              >
                <X size={12} />
              </button>
            )}
          </label>
        </div>
        <div className="table-scroll admin-users-scroll">
          <table className="data-table admin-users">
            <thead>
              <tr>
                <th>{text("用户", "User")}</th>
                <th>{text("角色", "Role")}</th>
                <th>{text("状态", "Status")}</th>
                <th>{text("最近登录", "Last login")}</th>
                <th>{text("会话", "Sessions")}</th>
              </tr>
            </thead>
            <tbody>
              {filteredUsers.map((user) => {
                const isSelf = user.id === currentUser.id;
                return (
                  <tr key={user.id} className={!user.enabled ? "is-muted" : ""}>
                    <td data-label={text("用户", "User")}>
                      <div className="admin-user-identity">
                        <span className="admin-user-avatar">
                          {user.username.slice(0, 1).toLocaleUpperCase(locale)}
                        </span>
                        <div>
                          <strong>{user.username}</strong>
                          <small>
                            {isSelf && (
                              <em>{text("当前账户", "you")}</em>
                            )}
                            {text("创建于", "created")}{" "}
                            {formatDate(user.created_at, locale)}
                          </small>
                        </div>
                      </div>
                    </td>
                    <td data-label={text("角色", "Role")}>
                      <select
                        value={user.role}
                        disabled={isSelf || update.isPending}
                        aria-label={text(
                          `修改 ${user.username} 的角色`,
                          `Change role for ${user.username}`,
                        )}
                        title={
                          isSelf
                            ? text(
                                "不能在这里修改自己的管理员角色",
                                "You cannot change your own administrator role here",
                              )
                            : undefined
                        }
                        onChange={(event) => {
                          const nextRole = event.target.value as UserRole;
                          if (nextRole !== user.role) {
                            setNotice(null);
                            setConfirmAction({
                              kind: "role",
                              user,
                              nextRole,
                            });
                          }
                        }}
                      >
                        <option value="user">
                          {text("普通用户", "user")}
                        </option>
                        <option value="admin">
                          {text("管理员", "admin")}
                        </option>
                      </select>
                    </td>
                    <td data-label={text("状态", "Status")}>
                      <button
                        className={`admin-account-state ${
                          user.enabled ? "admin-account-state--on" : ""
                        }`}
                        type="button"
                        disabled={isSelf || update.isPending}
                        title={
                          isSelf
                            ? text(
                                "不能停用当前账户",
                                "The current account cannot be disabled",
                              )
                            : undefined
                        }
                        onClick={() => {
                          setNotice(null);
                          if (user.enabled) {
                            setConfirmAction({
                              kind: "status",
                              user,
                              nextEnabled: false,
                            });
                          } else {
                            update.mutate({
                              id: user.id,
                              payload: { enabled: true },
                            });
                          }
                        }}
                      >
                        <i />
                        {user.enabled
                          ? text("已启用", "Enabled")
                          : text("已停用", "Disabled")}
                      </button>
                    </td>
                    <td data-label={text("最近登录", "Last login")}>
                      <span className="admin-last-login">
                        <Clock3 size={12} />
                        {user.last_login_at
                          ? formatDate(user.last_login_at, locale, true)
                          : text("从未登录", "Never")}
                      </span>
                    </td>
                    <td data-label={text("会话", "Sessions")}>
                      <button
                        className="button button--ghost button--small admin-session-button"
                        type="button"
                        disabled={revoke.isPending}
                        onClick={() => {
                          setNotice(null);
                          setConfirmAction({ kind: "sessions", user });
                        }}
                      >
                        <KeyRound size={13} />
                        {isSelf
                          ? text("撤销其他会话", "Revoke others")
                          : text("全部登出", "Sign out all")}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {!users.isLoading && filteredUsers.length === 0 && (
            <div className="admin-users-empty">
              <Search size={20} />
              <strong>{text("没有匹配账户", "No matching accounts")}</strong>
              <span>
                {text(
                  "换一个账户名或角色关键词。",
                  "Try another username or role keyword.",
                )}
              </span>
            </div>
          )}
        </div>
      </section>

      <ServerPanel
        error={monitor.isError}
        fetching={monitor.isFetching}
        locale={locale}
        monitor={monitor.data}
        onRefresh={() => void monitor.refetch()}
        text={text}
      />

      {showCreate && (
        <Modal
          title={text("创建平台账户", "Create platform account")}
          onClose={() => {
            if (!create.isPending) setShowCreate(false);
          }}
          text={text}
        >
          <form className="form admin-account-form" onSubmit={submitUser}>
            <div className="admin-form-intro">
              <UserRound size={18} />
              <div>
                <strong>
                  {text("为团队成员分配访问权限", "Provision team access")}
                </strong>
                <span>
                  {text(
                    "账户创建后立即生效，不需要邮箱验证。",
                    "The account becomes active immediately; no email verification is required.",
                  )}
                </span>
              </div>
            </div>
            <label className="field">
              <span>{text("账户名", "Account name")}</span>
              <input
                autoFocus
                name="username"
                minLength={2}
                maxLength={32}
                autoComplete="username"
                placeholder={text("例如：researcher-01", "e.g. researcher-01")}
                required
              />
              <small>
                {text("2–32 个字符。", "Between 2 and 32 characters.")}
              </small>
            </label>
            <label className="field">
              <span>{text("初始密码", "Initial password")}</span>
              <input
                name="password"
                type="password"
                minLength={8}
                maxLength={256}
                autoComplete="new-password"
                required
              />
              <small>
                {text(
                  "至少 8 位；请通过安全渠道交给用户。",
                  "At least 8 characters; share it through a secure channel.",
                )}
              </small>
            </label>
            <label className="field">
              <span>{text("初始角色", "Initial role")}</span>
              <select name="role" defaultValue="user">
                <option value="user">{text("普通用户", "User")}</option>
                <option value="admin">
                  {text("管理员 — 完整平台权限", "Administrator — full access")}
                </option>
              </select>
            </label>
            {create.error && (
              <div className="inline-error">
                {create.error instanceof Error
                  ? create.error.message
                  : String(create.error)}
              </div>
            )}
            <div className="modal__actions">
              <button
                className="button button--ghost"
                type="button"
                disabled={create.isPending}
                onClick={() => setShowCreate(false)}
              >
                {text("取消", "Cancel")}
              </button>
              <button className="button" disabled={create.isPending}>
                <Plus size={14} />
                {create.isPending
                  ? text("创建中…", "Creating…")
                  : text("创建账户", "Create account")}
              </button>
            </div>
          </form>
        </Modal>
      )}

      {confirmAction && (
        <AccountActionDialog
          action={confirmAction}
          error={update.error ?? revoke.error}
          pending={update.isPending || revoke.isPending}
          onClose={() => {
            if (!update.isPending && !revoke.isPending) setConfirmAction(null);
          }}
          onConfirm={runAccountAction}
          text={text}
        />
      )}
    </>
  );
}

function ServerPanel({
  error,
  fetching,
  locale,
  monitor,
  onRefresh,
  text,
}: {
  error: boolean;
  fetching: boolean;
  locale: string;
  monitor?: ServerMonitor;
  onRefresh: () => void;
  text: TextFn;
}) {
  const api = monitor?.api;
  const runner = monitor?.runner;
  const memoryTotal = Number(api?.memory_total ?? 0);
  const memoryUsed = Number(api?.memory_used ?? 0);
  const diskTotal = Number(api?.disk_total ?? 0);
  const diskUsed = Number(api?.disk_used ?? 0);
  const loadRatio =
    Number(api?.load_1 ?? 0) / Math.max(1, Number(api?.cpu_count ?? 1));
  const memoryRatio = memoryTotal ? memoryUsed / memoryTotal : 0;
  const diskRatio = diskTotal ? diskUsed / diskTotal : 0;
  const databaseRatio = Math.min(
    1,
    Number(monitor?.database.latency_ms ?? 0) / 500,
  );

  return (
    <section className="panel admin-monitor">
      <div className="panel-heading admin-monitor__heading">
        <div className="panel-heading__icon">
          <Server size={16} />
        </div>
        <div>
          <h3>{text("服务器监控", "Server monitoring")}</h3>
          <span>
            {monitor?.observed_at
              ? text(
                  `每 5 秒自动刷新 · ${formatDate(monitor.observed_at, locale, true)}`,
                  `Refreshes every 5 seconds · ${formatDate(monitor.observed_at, locale, true)}`,
                )
              : text("正在等待遥测数据", "Waiting for telemetry")}
          </span>
        </div>
        <button
          className="icon-button admin-monitor__refresh"
          type="button"
          disabled={fetching}
          aria-label={text("刷新服务器监控", "Refresh server monitoring")}
          onClick={onRefresh}
        >
          <RefreshCw className={fetching ? "spin" : undefined} size={15} />
        </button>
      </div>
      {error && (
        <div className="admin-monitor__stale">
          <AlertTriangle size={14} />
          {text(
            "本次刷新失败，下面可能是上一次成功采样的数据。",
            "Refresh failed; the values below may be from the last successful sample.",
          )}
        </div>
      )}
      <div className="monitor-grid">
        <MonitorMetric
          icon={<Cpu />}
          label={text("CPU 负载", "CPU load")}
          value={`${Number(api?.load_1 ?? 0).toFixed(2)} / ${api?.cpu_count ?? "—"}`}
          ratio={loadRatio}
          text={text}
        />
        <MonitorMetric
          icon={<MemoryStick />}
          label={text("内存", "Memory")}
          value={`${formatBytes(memoryUsed)} / ${formatBytes(memoryTotal)}`}
          ratio={memoryRatio}
          text={text}
        />
        <MonitorMetric
          icon={<HardDrive />}
          label={text("磁盘", "Disk")}
          value={`${formatBytes(diskUsed)} / ${formatBytes(diskTotal)}`}
          ratio={diskRatio}
          text={text}
        />
        <MonitorMetric
          icon={<Database />}
          label="PostgreSQL"
          value={`${monitor?.database.latency_ms ?? "—"} ms`}
          ratio={databaseRatio}
          text={text}
        />
      </div>
      <div className="admin-runtime-grid">
        <RuntimeFact
          label={text("API 在线时间", "API uptime")}
          value={formatUptime(Number(api?.uptime_seconds ?? 0), text)}
        />
        <RuntimeFact
          label={text("Docker 版本", "Docker version")}
          value={String(runner?.docker_version ?? "—")}
        />
        <RuntimeFact
          label={text("运行中容器", "Running containers")}
          value={String(runner?.containers_running ?? "—")}
        />
        <RuntimeFact
          label={text("本地镜像", "Local images")}
          value={String(runner?.images ?? "—")}
        />
        <RuntimeFact
          label={text("排队任务", "Queued runs")}
          value={String(monitor?.queue.queued ?? "—")}
        />
        <RuntimeFact
          label={text("工作槽位", "Worker slots")}
          value={`${runner?.workers_active ?? "—"} / ${runner?.worker_concurrency ?? "—"}`}
        />
      </div>
      {runner?.detail && !runner?.healthy && (
        <div className="admin-runner-detail">
          <AlertTriangle size={13} />
          <code>{String(runner.detail)}</code>
        </div>
      )}
    </section>
  );
}

function AdminStat({
  accent = false,
  detail,
  icon,
  label,
  value,
}: {
  accent?: boolean;
  detail: string;
  icon: React.ReactNode;
  label: string;
  value?: number;
}) {
  return (
    <article className={`stat-card admin-stat ${accent ? "is-active" : ""}`}>
      <div className="stat-card__icon">{icon}</div>
      <div>
        <span>{label}</span>
        <strong>{value ?? "—"}</strong>
        <small>{detail}</small>
      </div>
    </article>
  );
}

function PanelTitle({
  icon,
  subtitle,
  title,
}: {
  icon: React.ReactNode;
  subtitle?: string;
  title: string;
}) {
  return (
    <div className="panel-heading">
      <div className="panel-heading__icon">{icon}</div>
      <div>
        <h3>{title}</h3>
        {subtitle && <span>{subtitle}</span>}
      </div>
    </div>
  );
}

function HealthRow({
  label,
  state,
  text,
}: {
  label: string;
  state: "online" | "offline" | "checking";
  text: TextFn;
}) {
  return (
    <div>
      <span>
        <i
          className={`status-dot ${
            state === "online"
              ? "status-dot--safe"
              : state === "offline"
                ? "status-dot--danger"
                : ""
          }`}
        />
        {label}
      </span>
      <strong
        className={
          state === "online"
            ? "text-safe"
            : state === "offline"
              ? "text-danger"
              : undefined
        }
      >
        {state === "online"
          ? text("正常", "online")
          : state === "offline"
            ? text("异常", "offline")
            : text("检测中", "checking")}
      </strong>
    </div>
  );
}

function MonitorMetric({
  icon,
  label,
  ratio,
  text,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  ratio: number;
  text: TextFn;
  value: string;
}) {
  const boundedRatio = Math.max(0, Math.min(1, ratio));
  const width = `${boundedRatio * 100}%`;
  const tone =
    boundedRatio >= 0.9 ? "danger" : boundedRatio >= 0.75 ? "warning" : "safe";
  return (
    <div className={`monitor-metric monitor-metric--${tone}`}>
      <span>
        {icon}
        {label}
      </span>
      <div className="monitor-metric__value">
        <strong>{value}</strong>
        <small>
          {text("利用率", "utilization")}{" "}
          {Number.isFinite(boundedRatio)
            ? `${Math.round(boundedRatio * 100)}%`
            : "—"}
        </small>
      </div>
      <div className="monitor-metric__bar">
        <i style={{ width }} />
      </div>
    </div>
  );
}

function RuntimeFact({ label, value }: { label: string; value: string }) {
  return (
    <div className="admin-runtime-fact">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function AccountActionDialog({
  action,
  error,
  onClose,
  onConfirm,
  pending,
  text,
}: {
  action: AccountAction;
  error: Error | null;
  onClose: () => void;
  onConfirm: () => void;
  pending: boolean;
  text: TextFn;
}) {
  const roleChange = action.kind === "role";
  const disabling =
    action.kind === "status" && action.nextEnabled === false;
  const title = roleChange
    ? text("确认修改账户角色？", "Confirm role change?")
    : disabling
      ? text("确认停用账户？", "Disable this account?")
      : text("确认撤销会话？", "Revoke account sessions?");
  const body = roleChange
    ? text(
        `你将把 ${action.user.username} 的角色改为 ${
          action.nextRole === "admin" ? "管理员" : "普通用户"
        }。权限变更会立即生效。`,
        `You are changing ${action.user.username} to ${
          action.nextRole === "admin" ? "administrator" : "user"
        }. The privilege change takes effect immediately.`,
      )
    : disabling
      ? text(
          `${action.user.username} 将无法再次登录，现有会话也会立即失效。历史运行不会被删除。`,
          `${action.user.username} will no longer be able to sign in and existing sessions will be revoked. Historical runs are retained.`,
        )
      : text(
          action.user.id
            ? `${action.user.username} 的活动会话将失效。若这是你自己，当前浏览器会话会保留。`
            : "活动会话将失效。",
          `Active sessions for ${action.user.username} will be revoked. If this is you, the current browser session is preserved.`,
        );

  return (
    <Modal title={title} onClose={onClose} text={text}>
      <div className="destructive-confirmation">
        <div className="destructive-confirmation__warning">
          <AlertTriangle size={22} />
          <div>
            <strong>{title}</strong>
            <p>{body}</p>
          </div>
        </div>
        <dl>
          <div>
            <dt>{text("账户", "Account")}</dt>
            <dd>{action.user.username}</dd>
          </div>
          <div>
            <dt>{text("当前角色", "Current role")}</dt>
            <dd>{action.user.role}</dd>
          </div>
          <div>
            <dt>{text("操作", "Operation")}</dt>
            <dd>
              {roleChange
                ? `${action.user.role} → ${action.nextRole}`
                : disabling
                  ? "enabled → disabled"
                  : "revoke_sessions"}
            </dd>
          </div>
        </dl>
        {error && <div className="inline-error">{error.message}</div>}
        <div className="modal__actions">
          <button
            className="button button--ghost"
            type="button"
            disabled={pending}
            onClick={onClose}
          >
            {text("返回", "Go back")}
          </button>
          <button
            className={`button ${
              roleChange && action.nextRole === "admin"
                ? "button--warning"
                : "button--danger"
            }`}
            type="button"
            disabled={pending}
            onClick={onConfirm}
          >
            {pending
              ? text("正在应用…", "Applying…")
              : text("确认操作", "Confirm action")}
          </button>
        </div>
      </div>
    </Modal>
  );
}

function Modal({
  children,
  onClose,
  text,
  title,
}: {
  children: React.ReactNode;
  onClose: () => void;
  text: TextFn;
  title: string;
}) {
  return (
    <div
      className="modal-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.currentTarget === event.target) onClose();
      }}
    >
      <section
        className="modal admin-modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="modal__head">
          <h2>{title}</h2>
          <button
            className="icon-button"
            type="button"
            aria-label={text("关闭", "Close")}
            onClick={onClose}
          >
            <X size={15} />
          </button>
        </div>
        {children}
      </section>
    </div>
  );
}

function healthState(
  ready: boolean,
  value: number | string | boolean | null | undefined,
): "online" | "offline" | "checking" {
  if (!ready) return "checking";
  return value ? "online" : "offline";
}

function formatBytes(value: number) {
  if (!value) return "—";
  const gib = value / 1024 / 1024 / 1024;
  return `${gib.toFixed(gib >= 10 ? 0 : 1)} GiB`;
}

function formatDate(value: string, locale: string, withTime = false) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "—";
  return parsed.toLocaleString(locale, {
    year: "numeric",
    month: "short",
    day: "numeric",
    ...(withTime
      ? {
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        }
      : {}),
  });
}

function formatUptime(seconds: number, text: TextFn) {
  if (!seconds) return "—";
  const days = Math.floor(seconds / 86_400);
  const hours = Math.floor((seconds % 86_400) / 3_600);
  const minutes = Math.floor((seconds % 3_600) / 60);
  if (days) return text(`${days} 天 ${hours} 小时`, `${days}d ${hours}h`);
  if (hours) return text(`${hours} 小时 ${minutes} 分`, `${hours}h ${minutes}m`);
  return text(`${minutes} 分钟`, `${minutes}m`);
}

function setFailure(
  cause: unknown,
  setter: (notice: Notice | null) => void,
) {
  setter({
    tone: "danger",
    message: cause instanceof Error ? cause.message : String(cause),
  });
}

function refreshAdmin(queryClient: ReturnType<typeof useQueryClient>) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: ["admin-users"] }),
    queryClient.invalidateQueries({ queryKey: ["admin-summary"] }),
  ]);
}
