import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  KeyRound,
  Languages,
  ShieldCheck,
  Skull,
  UserPlus,
} from "lucide-react";
import { type FormEvent, useState } from "react";
import { api } from "../lib/api";
import { useLocale } from "../lib/i18n";
import type { AuthConfig, AuthResponse } from "../lib/types";

type AuthMode = "login" | "register" | "setup";

export default function AuthScreen({ config }: { config: AuthConfig }) {
  const queryClient = useQueryClient();
  const { isChinese, text, toggle } = useLocale();
  const [mode, setMode] = useState<AuthMode>(
    config.setup_required ? "setup" : "login",
  );
  const [error, setError] = useState("");
  const authenticate = useMutation({
    mutationFn: ({
      selectedMode,
      payload,
    }: {
      selectedMode: AuthMode;
      payload: Record<string, unknown>;
    }) => {
      if (selectedMode === "setup") return api.setup(payload);
      if (selectedMode === "register") return api.register(payload);
      return api.login(payload);
    },
    onSuccess: (result: AuthResponse) => {
      queryClient.setQueryData(["me"], result);
      queryClient.setQueryData<AuthConfig>(["auth-config"], {
        ...config,
        setup_required: false,
      });
      setError("");
    },
    onError: (cause) =>
      setError(cause instanceof Error ? cause.message : String(cause)),
  });

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const password = String(data.get("password") ?? "");
    const confirm = String(data.get("confirm_password") ?? "");
    if (mode !== "login" && password !== confirm) {
      setError(text("两次输入的密码不一致。", "Passwords do not match."));
      return;
    }
    authenticate.mutate({
      selectedMode: mode,
      payload: {
        username: data.get("username"),
        password,
        ...(mode !== "login"
          ? {
              setup_token: data.get("setup_token") || null,
            }
          : {}),
      },
    });
  };

  return (
    <main className="auth-shell">
      <button className="auth-language" type="button" onClick={toggle}>
        <Languages size={14} /> {isChinese ? "EN" : "中文"}
      </button>
      <section className="auth-card">
        <div className="auth-brand">
          <span>
            <Skull size={27} />
          </span>
          <div>
            <strong>The Evil Repository</strong>
            <small>EvilBench v{config.version}</small>
          </div>
        </div>
        <div className="auth-copy">
          <span className="eyebrow">
            {mode === "setup"
              ? text("首次初始化", "INITIAL SETUP")
              : mode === "register"
                ? text("创建账户", "CREATE ACCOUNT")
                : text("身份验证", "AUTHENTICATION")}
          </span>
          <h1>
            {mode === "setup"
              ? text("建立第一个管理员。", "Create the first administrator.")
              : mode === "register"
                ? text("进入调查现场。", "Enter the investigation.")
                : text("欢迎回来。", "Welcome back.")}
          </h1>
          <p>
            {mode === "setup"
              ? text(
                  "这个账户拥有用户、注册策略与服务器监控权限。",
                  "This account controls users, registration policy, and server monitoring.",
                )
              : text(
                  "账户会话使用 HttpOnly Cookie，并由 CSRF Token 保护写操作。",
                  "Sessions use HttpOnly cookies and CSRF-protected mutations.",
                )}
          </p>
        </div>
        <form className="auth-form" onSubmit={submit}>
          <label>
            <span>{text("账户名", "Account name")}</span>
            <input
              name="username"
              required
              minLength={2}
              maxLength={32}
              autoComplete="username"
            />
            {mode !== "login" && (
              <small>
                {text(
                  "2–32 位，可使用中文、字母、数字、点、横线和下划线",
                  "2–32 characters: letters, numbers, dots, hyphens, and underscores",
                )}
              </small>
            )}
          </label>
          <label>
            <span>{text("密码", "Password")}</span>
            <input
              name="password"
              type="password"
              required
              minLength={mode === "login" ? 1 : 8}
              autoComplete={
                mode === "login" ? "current-password" : "new-password"
              }
            />
            {mode !== "login" && (
              <small>{text("至少 8 个字符", "At least 8 characters")}</small>
            )}
          </label>
          {mode !== "login" && (
            <label>
              <span>{text("确认密码", "Confirm password")}</span>
              <input
                name="confirm_password"
                type="password"
                required
                minLength={8}
                autoComplete="new-password"
              />
            </label>
          )}
          {mode === "setup" && config.setup_token_required && (
            <label>
              <span>Setup Token</span>
              <input name="setup_token" type="password" required />
            </label>
          )}
          {error && <div className="inline-error">{error}</div>}
          <button
            className="button button--large"
            disabled={authenticate.isPending}
          >
            {mode === "register" ? (
              <UserPlus size={16} />
            ) : (
              <KeyRound size={16} />
            )}
            {mode === "setup"
              ? text("完成初始化", "Complete setup")
              : mode === "register"
                ? text("创建账户", "Create account")
                : text("登录", "Sign in")}
          </button>
        </form>
        {!config.setup_required && config.registration_enabled && (
          <button
            className="auth-mode"
            type="button"
            onClick={() => {
              setMode((current) =>
                current === "login" ? "register" : "login",
              );
              setError("");
            }}
          >
            {mode === "register"
              ? text("已有账户？返回登录", "Already registered? Sign in")
              : text(
                  "开放注册中 · 创建新账户",
                  "Registration is open · Create an account",
                )}
          </button>
        )}
        <footer className="auth-foot">
          <ShieldCheck size={13} />
          {text(
            "Provider 密钥只保存在控制平面",
            "Provider secrets remain in the control plane",
          )}
        </footer>
      </section>
    </main>
  );
}
