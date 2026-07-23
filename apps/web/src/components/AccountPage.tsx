import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Clock3,
  KeyRound,
  MonitorSmartphone,
  ShieldCheck,
  UserRound,
} from "lucide-react";
import { type FormEvent, useState } from "react";
import { api } from "../lib/api";
import { useLocale } from "../lib/i18n";
import type { AuthResponse, UserAccount } from "../lib/types";

export default function AccountPage({ user }: { user: UserAccount }) {
  const { locale, text } = useLocale();
  const queryClient = useQueryClient();
  const sessions = useQuery({ queryKey: ["sessions"], queryFn: api.sessions });
  const [message, setMessage] = useState("");
  const update = useMutation({
    mutationFn: api.updateAccount,
    onSuccess: (updated) => {
      queryClient.setQueryData<AuthResponse>(["me"], (current) =>
        current ? { ...current, user: updated } : current,
      );
      setMessage(text("账户已更新。", "Account updated."));
    },
    onError: (cause) =>
      setMessage(cause instanceof Error ? cause.message : String(cause)),
  });
  const revoke = useMutation({
    mutationFn: api.revokeSession,
    onSuccess: () =>
      void queryClient.invalidateQueries({ queryKey: ["sessions"] }),
  });
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    update.mutate({
      username: data.get("username"),
      current_password: data.get("current_password") || null,
      new_password: data.get("new_password") || null,
    });
  };

  return (
    <>
      <div className="page-header">
        <div>
          <span className="eyebrow">
            {text("账户安全", "ACCOUNT SECURITY")}
          </span>
          <h1>{text("个人账户。", "Your account.")}</h1>
          <p>
            {text(
              "管理账户名、密码以及当前有效的登录会话。",
              "Manage your account name, password, and active login sessions.",
            )}
          </p>
        </div>
      </div>
      <div className="settings-grid">
        <section className="panel">
          <div className="panel-heading">
            <div className="panel-heading__icon">
              <UserRound size={16} />
            </div>
            <div>
              <h3>{text("账户资料", "Account profile")}</h3>
              <span>{user.username}</span>
            </div>
          </div>
          <form className="form" onSubmit={submit}>
            <label className="field">
              <span>{text("账户名", "Account name")}</span>
              <input
                name="username"
                defaultValue={user.username}
                minLength={2}
                maxLength={32}
                autoComplete="username"
                required
              />
            </label>
            <div className="account-role">
              <ShieldCheck size={14} />
              <span>{text("角色", "Role")}</span>
              <strong>{user.role}</strong>
            </div>
            <label className="field">
              <span>{text("当前密码", "Current password")}</span>
              <input
                name="current_password"
                type="password"
                autoComplete="current-password"
              />
            </label>
            <label className="field">
              <span>{text("新密码", "New password")}</span>
              <input
                name="new_password"
                type="password"
                minLength={12}
                autoComplete="new-password"
              />
              <small>
                {text(
                  "留空则不修改密码",
                  "Leave blank to keep the current password",
                )}
              </small>
            </label>
            {message && <div className="inline-message">{message}</div>}
            <button className="button" disabled={update.isPending}>
              <KeyRound size={14} /> {text("保存账户", "Save account")}
            </button>
          </form>
        </section>
        <section className="panel">
          <div className="panel-heading">
            <div className="panel-heading__icon">
              <MonitorSmartphone size={16} />
            </div>
            <div>
              <h3>{text("登录会话", "Login sessions")}</h3>
              <span>
                {text(
                  "撤销不认识的设备",
                  "Revoke devices you do not recognize",
                )}
              </span>
            </div>
          </div>
          <div className="session-list">
            {(sessions.data ?? []).map((item) => (
              <div className="session-row" key={item.id}>
                <MonitorSmartphone size={17} />
                <div>
                  <strong>
                    {item.current
                      ? text("当前会话", "Current session")
                      : item.user_agent || text("未知客户端", "Unknown client")}
                  </strong>
                  <small>
                    {item.ip_address ?? "—"} · <Clock3 size={11} />
                    {new Date(item.last_seen_at).toLocaleString(locale)}
                  </small>
                </div>
                {!item.current && (
                  <button
                    className="button button--ghost button--small"
                    onClick={() => revoke.mutate(item.id)}
                  >
                    {text("撤销", "Revoke")}
                  </button>
                )}
              </div>
            ))}
          </div>
        </section>
      </div>
    </>
  );
}
