import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  Copy,
  ExternalLink,
  FileJson2,
  KeyRound,
  LoaderCircle,
  Pencil,
  Plus,
  RefreshCw,
  ShieldCheck,
  SquareTerminal,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { type FormEvent, type ReactNode, useEffect, useState } from "react";
import { api } from "../lib/api";
import { useLocale } from "../lib/i18n";
import type {
  CredentialKind,
  CredentialStatus,
  OAuthDeviceStart,
  ProviderCredential,
  UserAccount,
} from "../lib/types";

type CreateMode =
  | "api_key"
  | "antigravity"
  | "anthropic_token"
  | "codex_import"
  | "codex_device";

export default function CredentialsPage({
  currentUser,
}: {
  currentUser: UserAccount;
}) {
  const { locale, text } = useLocale();
  const queryClient = useQueryClient();
  const credentials = useQuery({
    queryKey: ["credentials"],
    queryFn: api.credentials,
  });
  const [mode, setMode] = useState<CreateMode | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<ProviderCredential | null>(
    null,
  );
  const [replaceTarget, setReplaceTarget] = useState<ProviderCredential | null>(
    null,
  );
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const refresh = useMutation({
    mutationFn: api.refreshCredential,
    onSuccess: () => {
      setError("");
      setNotice("");
      void queryClient.invalidateQueries({ queryKey: ["credentials"] });
      void queryClient.invalidateQueries({ queryKey: ["models"] });
    },
    onError: (cause) =>
      setError(cause instanceof Error ? cause.message : String(cause)),
  });
  const sync = useMutation({
    mutationFn: api.syncCredentialModels,
    onSuccess: (result) => {
      setError("");
      setNotice(
        result.provider === "anthropic"
          ? text(
              `已配置 ${result.discovered} 个 Claude Code 官方模型别名；新增 ${result.created} 个，已有 ${result.existing} 个。实际权限会在运行时由 Anthropic 校验。`,
              `Provisioned ${result.discovered} official Claude Code model aliases; ${result.created} created and ${result.existing} already present. Anthropic validates entitlement at runtime.`,
            )
          : text(
              `账户返回 ${result.discovered} 个可选模型；新增 ${result.created} 个，已有 ${result.existing} 个。`,
              `The account returned ${result.discovered} selectable models; ${result.created} created and ${result.existing} already present.`,
            ),
      );
      void queryClient.invalidateQueries({ queryKey: ["credentials"] });
      void queryClient.invalidateQueries({ queryKey: ["models"] });
    },
    onError: (cause) => {
      setNotice("");
      setError(cause instanceof Error ? cause.message : String(cause));
    },
  });
  const remove = useMutation({
    mutationFn: api.deleteCredential,
    onSuccess: () => {
      setDeleteTarget(null);
      setError("");
      void queryClient.invalidateQueries({ queryKey: ["credentials"] });
    },
    onError: (cause) =>
      setError(cause instanceof Error ? cause.message : String(cause)),
  });
  const replace = useMutation({
    mutationFn: ({ id, secret }: { id: string; secret: string }) =>
      api.updateCredential(id, { secret }),
    onSuccess: () => {
      setReplaceTarget(null);
      setError("");
      setNotice(
        text(
          "凭据已替换；后续 Provider 请求会使用新密文。",
          "Credential replaced; subsequent Provider requests use the new secret.",
        ),
      );
      void queryClient.invalidateQueries({ queryKey: ["credentials"] });
    },
    onError: (cause) =>
      setError(cause instanceof Error ? cause.message : String(cause)),
  });

  return (
    <>
      <div className="page-header">
        <div>
          <span className="eyebrow">
            {text("认证中心", "AUTHENTICATION VAULT")}
          </span>
          <h1>{text("Provider 凭据。", "Provider credentials.")}</h1>
          <p>
            {text(
              "集中保存 API Key、Claude Code 与 Codex 登录；Antigravity 认证由 Runner 内置的官方 agy 自己持有。任何认证材料都不会进入候选 Docker、工具输出或运行归档。",
              "Store API keys plus Claude Code and Codex sign-ins centrally. Antigravity authentication remains owned by the official agy binary bundled in the Runner. No authentication material enters candidate Docker, tool output, or run archives.",
            )}
          </p>
        </div>
        <button className="button" onClick={() => setMode("api_key")}>
          <Plus size={15} /> {text("添加凭据", "Add credential")}
        </button>
      </div>

      <section className="credential-security">
        <ShieldCheck size={18} />
        <div>
          <strong>{text("官方客户端边界", "Official client boundary")}</strong>
          <span>
            {text(
              "Claude Code OAuth 仅交给官方 Agent SDK；Antigravity 的登录、刷新、模型目录与请求全部交给官方 agy。平台不再导入 Gemini OAuth，也不直接反代私有 Code Assist API。",
              "Claude Code OAuth is consumed only by the official Agent SDK. Antigravity sign-in, refresh, model discovery, and requests are owned by official agy. The platform no longer imports Gemini OAuth or directly proxies private Code Assist APIs.",
            )}
          </span>
        </div>
      </section>

      {error && (
        <div className="inline-error credential-page-error">
          <AlertTriangle size={14} />
          {error}
        </div>
      )}
      {notice && (
        <div className="credential-sync-notice">
          <CheckCircle2 size={14} />
          {notice}
        </div>
      )}

      <div className="credential-actions">
        <CredentialAction
          icon={<KeyRound size={19} />}
          title="API Key"
          description={text(
            "适用于 OpenAI、Anthropic、兼容端点和 Gemini API。",
            "For OpenAI, Anthropic, compatible endpoints, and the Gemini API.",
          )}
          action={text("添加密钥", "Add key")}
          onClick={() => setMode("api_key")}
        />
        <CredentialAction
          icon={<ShieldCheck size={19} />}
          title={text("Claude Code OAuth", "Claude Code OAuth")}
          description={text(
            "使用 claude setup-token 生成的订阅令牌；不模拟 Claude.ai 登录。",
            "Use a subscription token from claude setup-token; no simulated Claude.ai login.",
          )}
          action={text("添加令牌", "Add token")}
          onClick={() => setMode("anthropic_token")}
        />
        <CredentialAction
          icon={<FileJson2 size={19} />}
          title={text("导入 Codex OAuth", "Import Codex OAuth")}
          description={text(
            "导入 Codex CLI auth.json；Gemini OAuth 文件不再支持。",
            "Import Codex CLI auth.json. Gemini OAuth files are no longer supported.",
          )}
          action={text("选择文件", "Choose file")}
          onClick={() => setMode("codex_import")}
        />
        <CredentialAction
          icon={<ExternalLink size={19} />}
          title={text("Codex 设备登录", "Codex device sign-in")}
          description={text(
            "无需把 auth.json 从另一台机器复制到服务器。",
            "Sign in without copying auth.json from another machine.",
          )}
          action={text("开始登录", "Start sign-in")}
          onClick={() => setMode("codex_device")}
        />
        {currentUser.role === "admin" && (
          <CredentialAction
            icon={<SquareTerminal size={19} />}
            title="Antigravity CLI"
            description={text(
              "在部署容器内登录官方 agy，再自动读取该账户实际可用模型。",
              "Sign in to official agy inside the deployment, then discover the account's actual models.",
            )}
            action={text("连接 CLI", "Attach CLI")}
            onClick={() => setMode("antigravity")}
          />
        )}
      </div>

      <div className="credential-grid">
        {(credentials.data ?? []).map((credential) => (
          <article className="credential-card" key={credential.id}>
            <div className="credential-card__head">
              <div
                className={`credential-kind credential-kind--${credential.kind}`}
              >
                {credential.kind === "api_key" ? (
                  <KeyRound size={17} />
                ) : (
                  <ShieldCheck size={17} />
                )}
              </div>
              <div>
                <h3>{credential.name}</h3>
                <span>{kindLabel(credential.kind)}</span>
              </div>
              <CredentialStatusBadge status={credential.status} text={text} />
            </div>
            <dl>
              <div>
                <dt>{text("账户", "Account")}</dt>
                <dd>{credential.account_hint ?? "—"}</dd>
              </div>
              <div>
                <dt>{text("模型引用", "Model profiles")}</dt>
                <dd>{credential.model_count}</dd>
              </div>
              <div>
                <dt>{text("到期", "Expires")}</dt>
                <dd>
                  {credential.expires_at
                    ? new Date(credential.expires_at).toLocaleString(locale)
                    : text("不适用 / 未知", "N/A / unknown")}
                </dd>
              </div>
              <div>
                <dt>{text("最近刷新", "Last refresh")}</dt>
                <dd>
                  {credential.last_refreshed_at
                    ? new Date(credential.last_refreshed_at).toLocaleString(
                        locale,
                      )
                    : "—"}
                </dd>
              </div>
            </dl>
            {credential.last_error_code && (
              <code className="credential-card__error">
                {credential.last_error_code}
              </code>
            )}
            <div className="credential-card__actions">
              {(credential.kind === "codex_oauth" ||
                credential.kind === "anthropic_oauth" ||
                credential.kind === "antigravity_cli") && (
                <button
                  className="button button--small"
                  disabled={sync.isPending && sync.variables === credential.id}
                  onClick={() => {
                    setNotice("");
                    setError("");
                    sync.mutate(credential.id);
                  }}
                >
                  {sync.isPending && sync.variables === credential.id ? (
                    <LoaderCircle className="spin" size={13} />
                  ) : (
                    <RefreshCw size={13} />
                  )}
                  {credential.model_count
                    ? text("同步模型", "Sync models")
                    : text("获取模型", "Fetch models")}
                </button>
              )}
              {credential.kind !== "anthropic_oauth" && (
                <button
                  className="button button--ghost button--small"
                  disabled={
                    refresh.isPending && refresh.variables === credential.id
                  }
                  onClick={() => refresh.mutate(credential.id)}
                >
                  <RefreshCw size={13} />
                  {credential.kind === "api_key"
                    ? text("重置状态", "Reset status")
                    : text("检查状态", "Check status")}
                </button>
              )}
              {(credential.kind === "api_key" ||
                credential.kind === "anthropic_oauth") && (
                <button
                  className="icon-button"
                  title={text("替换密文", "Replace secret")}
                  onClick={() => {
                    setError("");
                    setReplaceTarget(credential);
                  }}
                >
                  <Pencil size={14} />
                </button>
              )}
              <button
                className="icon-button icon-button--danger"
                title={text("删除凭据", "Delete credential")}
                onClick={() => {
                  setError("");
                  setDeleteTarget(credential);
                }}
              >
                <Trash2 size={14} />
              </button>
            </div>
          </article>
        ))}
      </div>

      {!credentials.isLoading && !credentials.data?.length && (
        <section className="empty-state credential-empty">
          <KeyRound size={25} />
          <h3>{text("还没有 Provider 凭据", "No provider credentials yet")}</h3>
          <p>
            {text(
              "先添加凭据，再在模型配置中选择它。",
              "Add a credential, then select it from a model profile.",
            )}
          </p>
        </section>
      )}

      {mode && (
        <CredentialModal
          mode={mode}
          onMode={setMode}
          onProvisionError={(message) => {
            setNotice("");
            setError(message);
          }}
          onClose={() => {
            setMode(null);
            setError("");
          }}
        />
      )}

      {deleteTarget && (
        <CredentialDialog
          title={text("删除这份凭据？", "Delete this credential?")}
          onClose={() => !remove.isPending && setDeleteTarget(null)}
        >
          <div className="destructive-confirmation">
            <div className="destructive-confirmation__warning">
              <AlertTriangle size={22} />
              <div>
                <strong>
                  {deleteTarget.kind === "antigravity_cli"
                    ? text(
                        "模型引用将被移除，但 agy 的部署会话不会自动登出。",
                        "The model reference will be removed, but the deployment's agy session is not logged out automatically.",
                      )
                    : text(
                        "加密令牌将被清除，且无法恢复。",
                        "The encrypted token will be erased and cannot be recovered.",
                      )}
                </strong>
                <p>
                  {deleteTarget.model_count
                    ? text(
                        `仍有 ${deleteTarget.model_count} 个模型配置引用它，删除会被阻止。`,
                        `${deleteTarget.model_count} model profile(s) still reference it, so deletion will be blocked.`,
                      )
                    : text(
                        "历史运行不会被删除。",
                        "Historical runs are not deleted.",
                      )}
                </p>
              </div>
            </div>
            {error && <div className="inline-error">{error}</div>}
            <div className="modal__actions">
              <button
                className="button button--ghost"
                disabled={remove.isPending}
                onClick={() => setDeleteTarget(null)}
              >
                {text("取消", "Cancel")}
              </button>
              <button
                className="button button--danger"
                disabled={remove.isPending || deleteTarget.model_count > 0}
                onClick={() => remove.mutate(deleteTarget.id)}
              >
                <Trash2 size={14} />
                {text("确认删除", "Delete credential")}
              </button>
            </div>
          </div>
        </CredentialDialog>
      )}

      {replaceTarget && (
        <CredentialDialog
          title={text("替换凭据", "Replace credential")}
          onClose={() => !replace.isPending && setReplaceTarget(null)}
        >
          <form
            className="form"
            onSubmit={(event) => {
              event.preventDefault();
              const data = new FormData(event.currentTarget);
              replace.mutate({
                id: replaceTarget.id,
                secret: String(data.get("secret") ?? ""),
              });
            }}
          >
            {replaceTarget.kind === "anthropic_oauth" && (
              <div className="credential-import-warning">
                <AlertTriangle size={16} />
                <span>
                  {text(
                    "先运行 `claude setup-token` 生成新令牌。保存后旧密文会被覆盖，现有模型引用无需修改。",
                    "Run `claude setup-token` first. Saving replaces the old ciphertext without changing existing model references.",
                  )}
                </span>
              </div>
            )}
            <label className="field">
              <span>{replaceTarget.name}</span>
              <input
                name="secret"
                type="password"
                required
                autoComplete="new-password"
                autoFocus
              />
            </label>
            {error && <div className="inline-error">{error}</div>}
            <ModalActions
              pending={replace.isPending}
              onClose={() => setReplaceTarget(null)}
              text={text}
              submitLabel={text("覆盖旧密文", "Replace encrypted secret")}
            />
          </form>
        </CredentialDialog>
      )}
    </>
  );
}

function CredentialAction({
  icon,
  title,
  description,
  action,
  onClick,
}: {
  icon: ReactNode;
  title: string;
  description: string;
  action: string;
  onClick: () => void;
}) {
  return (
    <button className="credential-action" onClick={onClick}>
      <span>{icon}</span>
      <div>
        <strong>{title}</strong>
        <small>{description}</small>
      </div>
      <em>{action}</em>
    </button>
  );
}

function CredentialModal({
  mode,
  onMode,
  onClose,
  onProvisionError,
}: {
  mode: CreateMode;
  onMode: (mode: CreateMode) => void;
  onClose: () => void;
  onProvisionError: (message: string) => void;
}) {
  const { text } = useLocale();
  const queryClient = useQueryClient();
  const [error, setError] = useState("");
  const [device, setDevice] = useState<OAuthDeviceStart | null>(null);
  const [deviceName, setDeviceName] = useState("Codex OAuth");
  const [deviceComplete, setDeviceComplete] = useState(false);
  const title = {
    api_key: text("添加 API Key", "Add API key"),
    antigravity: text(
      "连接官方 Antigravity CLI",
      "Attach official Antigravity CLI",
    ),
    anthropic_token: text("添加 Claude Code OAuth", "Add Claude Code OAuth"),
    codex_import: text("导入 Codex auth.json", "Import Codex auth.json"),
    codex_device: text("Codex 设备登录", "Codex device sign-in"),
  }[mode];
  const create = useMutation({
    mutationFn: api.createCredential,
    onSuccess: (credential) => finish(credential),
    onError: showError,
  });
  const importFile = useMutation({
    mutationFn: api.importCredential,
    onSuccess: (credential) => finish(credential),
    onError: showError,
  });
  const attachAntigravity = useMutation({
    mutationFn: api.attachAntigravityCredential,
    onSuccess: (credential) => finish(credential),
    onError: showError,
  });
  const beginDevice = useMutation({
    mutationFn: api.startCodexOAuth,
    onSuccess: (result) => {
      setError("");
      setDevice(result);
    },
    onError: showError,
  });

  function showError(cause: unknown) {
    setError(cause instanceof Error ? cause.message : String(cause));
  }

  async function syncOAuthCredential(credential: ProviderCredential) {
    if (
      credential.kind !== "codex_oauth" &&
      credential.kind !== "anthropic_oauth" &&
      credential.kind !== "antigravity_cli"
    ) {
      return;
    }
    await api.syncCredentialModels(credential.id);
  }

  async function finish(credential: ProviderCredential) {
    setError("");
    let provisionError = "";
    try {
      await syncOAuthCredential(credential);
    } catch (cause) {
      const detail = cause instanceof Error ? cause.message : String(cause);
      provisionError = text(
        `认证引用已保存，但账户模型自动同步失败：${detail}`,
        `The credential reference was saved, but automatic account-model sync failed: ${detail}`,
      );
    }
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["credentials"] }),
      queryClient.invalidateQueries({ queryKey: ["models"] }),
    ]);
    onClose();
    if (provisionError) onProvisionError(provisionError);
  }

  useEffect(() => {
    if (!device || deviceComplete) return;
    let stopped = false;
    let timer: number | undefined;
    const poll = async () => {
      if (stopped) return;
      if (Date.now() >= new Date(device.expires_at).getTime()) {
        setError(
          text(
            "设备代码已过期，请重新开始登录。",
            "The device code expired. Start sign-in again.",
          ),
        );
        return;
      }
      try {
        const result = await api.pollCodexOAuth({
          flow_token: device.flow_token,
          name: deviceName,
        });
        if (result.state === "complete") {
          if (result.credential) {
            try {
              await syncOAuthCredential(result.credential);
            } catch (cause) {
              const detail =
                cause instanceof Error ? cause.message : String(cause);
              setError(
                text(
                  `登录已完成，但账户模型自动同步失败：${detail}`,
                  `Sign-in completed, but automatic account-model sync failed: ${detail}`,
                ),
              );
            }
          }
          await Promise.all([
            queryClient.invalidateQueries({ queryKey: ["credentials"] }),
            queryClient.invalidateQueries({ queryKey: ["models"] }),
          ]);
          setDeviceComplete(true);
          return;
        }
        timer = window.setTimeout(poll, Math.max(device.interval, 2) * 1_000);
      } catch (cause) {
        if (!stopped) showError(cause);
      }
    };
    timer = window.setTimeout(poll, Math.max(device.interval, 2) * 1_000);
    return () => {
      stopped = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [device, deviceComplete, deviceName, queryClient, text]);

  const submitKey = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    create.mutate({
      name: data.get("name"),
      kind: "api_key",
      secret: data.get("secret"),
    });
  };

  const submitAnthropicToken = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    create.mutate({
      name: data.get("name"),
      kind: "anthropic_oauth",
      secret: data.get("secret"),
    });
  };

  const submitAntigravity = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    attachAntigravity.mutate({ name: data.get("name") });
  };

  const submitImport = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const file = data.get("document");
    if (!(file instanceof File) || !file.size) {
      setError(text("请选择 JSON 文件。", "Choose a JSON file."));
      return;
    }
    if (file.size > 65_536) {
      setError(
        text("认证文件不能超过 64 KiB。", "Auth files must be under 64 KiB."),
      );
      return;
    }
    try {
      const document = JSON.parse(await file.text()) as unknown;
      if (
        !document ||
        Array.isArray(document) ||
        typeof document !== "object"
      ) {
        throw new Error(
          text(
            "文件内容必须是 JSON 对象。",
            "The file must contain a JSON object.",
          ),
        );
      }
      importFile.mutate({
        name: data.get("name"),
        kind: "codex_oauth",
        document,
      });
    } catch (cause) {
      showError(cause);
    }
  };

  return (
    <CredentialDialog title={title} onClose={onClose}>
      <div className="credential-mode-tabs">
        <button
          className={mode === "api_key" ? "active" : ""}
          onClick={() => onMode("api_key")}
        >
          API Key
        </button>
        <button
          className={mode === "anthropic_token" ? "active" : ""}
          onClick={() => onMode("anthropic_token")}
        >
          Claude OAuth
        </button>
        <button
          className={mode === "antigravity" ? "active" : ""}
          onClick={() => onMode("antigravity")}
        >
          Antigravity
        </button>
        <button
          className={mode === "codex_import" ? "active" : ""}
          onClick={() => onMode("codex_import")}
        >
          Codex JSON
        </button>
        <button
          className={mode === "codex_device" ? "active" : ""}
          onClick={() => onMode("codex_device")}
        >
          Codex OAuth
        </button>
      </div>

      {mode === "api_key" && (
        <form className="form" onSubmit={submitKey}>
          <label className="field">
            <span>{text("凭据名称", "Credential name")}</span>
            <input
              name="name"
              required
              maxLength={120}
              placeholder="Provider key"
            />
          </label>
          <label className="field">
            <span>API Key</span>
            <input
              name="secret"
              type="password"
              required
              autoComplete="new-password"
            />
            <small>
              {text(
                "提交后不会再次显示明文。",
                "The plaintext is never displayed again after submission.",
              )}
            </small>
          </label>
          {error && <div className="inline-error">{error}</div>}
          <ModalActions
            pending={create.isPending}
            onClose={onClose}
            text={text}
          />
        </form>
      )}

      {mode === "antigravity" && (
        <form className="form" onSubmit={submitAntigravity}>
          <div className="credential-import-warning">
            <SquareTerminal size={16} />
            <span>
              {text(
                "镜像已内置并校验官方 agy 1.1.7。平台不会接收 auth.json、OAuth Token、Google 客户端密钥或账号密码；登录与刷新完全由 agy 处理。该会话属于整台部署，因此仅管理员可连接。",
                "The image includes a checksum-verified official agy 1.1.7. The platform never accepts auth.json, OAuth tokens, Google client secrets, or account passwords; agy owns sign-in and refresh. The session belongs to the deployment, so only administrators may attach it.",
              )}
            </span>
          </div>
          <div className="credential-device">
            <span>
              {text(
                "先在部署仓库目录执行",
                "First run this from the deployment repository",
              )}
            </span>
            <code>make antigravity-login</code>
            <small>
              {text(
                "云服务器会显示官方授权 URL；在本机浏览器登录后，把一次性代码贴回终端。登录完成后返回这里继续。",
                "A remote server prints the official authorization URL. Sign in in your local browser, then paste the one-time code back into the terminal. Return here after login completes.",
              )}
            </small>
          </div>
          <label className="field">
            <span>{text("凭据名称", "Credential name")}</span>
            <input
              name="name"
              required
              maxLength={120}
              defaultValue="Antigravity CLI"
            />
          </label>
          {error && <div className="inline-error">{error}</div>}
          <ModalActions
            pending={attachAntigravity.isPending}
            onClose={onClose}
            text={text}
            submitLabel={text(
              "连接会话并同步模型",
              "Attach session and sync models",
            )}
          />
        </form>
      )}

      {mode === "anthropic_token" && (
        <form className="form" onSubmit={submitAnthropicToken}>
          <div className="credential-import-warning">
            <AlertTriangle size={16} />
            <span>
              {text(
                "在安装了 Claude Code 的可信机器上运行 `claude setup-token`，完成网页授权后把输出的一年期令牌粘贴到这里。平台不会索取账号密码，也不会自行实现 Claude.ai OAuth 登录。该方式仅面向自托管的个人/组织内部部署；公开第三方服务应使用 Anthropic Console API Key。",
                "Run `claude setup-token` on a trusted machine with Claude Code installed, finish authorization, then paste the emitted one-year token here. The platform never asks for your password and does not implement Claude.ai login. This route is for self-hosted personal or internal deployments; public third-party services should use an Anthropic Console API key.",
              )}
            </span>
          </div>
          <label className="field">
            <span>{text("凭据名称", "Credential name")}</span>
            <input
              name="name"
              required
              maxLength={120}
              defaultValue="Claude Code OAuth"
            />
          </label>
          <label className="field">
            <span>CLAUDE_CODE_OAUTH_TOKEN</span>
            <input
              name="secret"
              type="password"
              required
              autoComplete="new-password"
            />
            <small>
              {text(
                "提交后不会再次显示明文；令牌不会进入候选环境或导出归档。",
                "The plaintext is never shown again and never enters candidate environments or exports.",
              )}
            </small>
          </label>
          {error && <div className="inline-error">{error}</div>}
          <ModalActions
            pending={create.isPending}
            onClose={onClose}
            text={text}
            submitLabel={text(
              "加密保存并获取模型",
              "Encrypt and provision models",
            )}
          />
        </form>
      )}

      {mode === "codex_import" && (
        <form className="form" onSubmit={submitImport}>
          <div className="credential-import-warning">
            <AlertTriangle size={16} />
            <span>
              {text(
                "选择 Codex CLI 的 auth.json。Refresh Token 会轮换，CLI 与平台长期共用同一份快照可能使其中一方失效；持续使用建议选择“Codex OAuth”设备登录。",
                "Choose Codex CLI auth.json. Refresh tokens rotate, so a snapshot shared by the CLI and platform can invalidate either copy; use Codex OAuth device sign-in for ongoing use.",
              )}
            </span>
          </div>
          <label className="field">
            <span>{text("凭据名称", "Credential name")}</span>
            <input
              name="name"
              required
              maxLength={120}
              defaultValue="Codex OAuth"
            />
          </label>
          <label className="credential-file">
            <Upload size={20} />
            <strong>auth.json</strong>
            <small>{text("最大 64 KiB", "64 KiB maximum")}</small>
            <input
              name="document"
              type="file"
              required
              accept=".json,application/json"
            />
          </label>
          {error && <div className="inline-error">{error}</div>}
          <ModalActions
            pending={importFile.isPending}
            onClose={onClose}
            text={text}
            submitLabel={text("加密导入", "Encrypt and import")}
          />
        </form>
      )}

      {mode === "codex_device" && (
        <div className="form">
          {!device ? (
            <>
              <label className="field">
                <span>{text("凭据名称", "Credential name")}</span>
                <input
                  value={deviceName}
                  maxLength={120}
                  onChange={(event) => setDeviceName(event.target.value)}
                />
              </label>
              <div className="credential-import-warning">
                <AlertTriangle size={16} />
                <span>
                  {text(
                    "这是实验性 Codex 订阅通道。它使用 Codex CLI 的官方登录端点；请自行确认账户与组织政策允许这种用法。",
                    "This is an experimental Codex subscription channel using Codex CLI sign-in endpoints. Confirm that your account and organization policies permit this use.",
                  )}
                </span>
              </div>
              {error && <div className="inline-error">{error}</div>}
              <div className="modal__actions">
                <button className="button button--ghost" onClick={onClose}>
                  {text("取消", "Cancel")}
                </button>
                <button
                  className="button"
                  disabled={beginDevice.isPending || !deviceName.trim()}
                  onClick={() => beginDevice.mutate()}
                >
                  {beginDevice.isPending ? (
                    <LoaderCircle className="spin" size={14} />
                  ) : (
                    <ExternalLink size={14} />
                  )}
                  {text("获取设备代码", "Get device code")}
                </button>
              </div>
            </>
          ) : deviceComplete ? (
            <div className="credential-device-complete">
              <CheckCircle2 size={35} />
              <strong>{text("登录完成", "Sign-in complete")}</strong>
              <span>
                {text(
                  "凭据已加密保存，可以在模型配置中使用。",
                  "The credential is encrypted and ready for model profiles.",
                )}
              </span>
              {error && <div className="inline-error">{error}</div>}
              <button className="button" onClick={onClose}>
                {text("完成", "Done")}
              </button>
            </div>
          ) : (
            <div className="credential-device">
              <LoaderCircle className="spin" size={21} />
              <span>
                {text(
                  "在浏览器中输入此代码",
                  "Enter this code in your browser",
                )}
              </span>
              <strong>{device.user_code}</strong>
              <div>
                <button
                  className="button button--ghost button--small"
                  onClick={() =>
                    void navigator.clipboard?.writeText(device.user_code)
                  }
                >
                  <Copy size={13} /> {text("复制", "Copy")}
                </button>
                <a
                  className="button button--small"
                  href={device.verification_uri}
                  target="_blank"
                  rel="noreferrer"
                >
                  <ExternalLink size={13} />{" "}
                  {text("打开登录页", "Open sign-in")}
                </a>
              </div>
              <small>
                {text(
                  "正在等待授权；完成网页步骤后会自动继续。",
                  "Waiting for authorization; this page continues automatically.",
                )}
              </small>
              {error && <div className="inline-error">{error}</div>}
            </div>
          )}
        </div>
      )}
    </CredentialDialog>
  );
}

function ModalActions({
  pending,
  onClose,
  text,
  submitLabel,
}: {
  pending: boolean;
  onClose: () => void;
  text: (chinese: string, english: string) => string;
  submitLabel?: string;
}) {
  return (
    <div className="modal__actions">
      <button
        className="button button--ghost"
        type="button"
        disabled={pending}
        onClick={onClose}
      >
        {text("取消", "Cancel")}
      </button>
      <button className="button" disabled={pending}>
        {pending ? (
          <LoaderCircle className="spin" size={14} />
        ) : (
          <KeyRound size={14} />
        )}
        {submitLabel ?? text("保存凭据", "Save credential")}
      </button>
    </div>
  );
}

function CredentialDialog({
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
      <section
        className="modal modal--credential"
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="modal__head">
          <h2>{title}</h2>
          <button className="icon-button" onClick={onClose} aria-label="Close">
            <X size={17} />
          </button>
        </div>
        {children}
      </section>
    </div>
  );
}

function CredentialStatusBadge({
  status,
  text,
}: {
  status: CredentialStatus;
  text: (chinese: string, english: string) => string;
}) {
  const labels: Record<CredentialStatus, string> = {
    ready: text("可用", "Ready"),
    unchecked: text("待验证", "Unchecked"),
    expired: text("已过期", "Expired"),
    needs_reauth: text("需重登", "Re-auth"),
    error: text("异常", "Error"),
  };
  return (
    <span className={`credential-status credential-status--${status}`}>
      {labels[status]}
    </span>
  );
}

function kindLabel(kind: CredentialKind) {
  const labels: Record<CredentialKind, string> = {
    api_key: "API KEY",
    antigravity_cli: "ANTIGRAVITY CLI",
    anthropic_oauth: "CLAUDE CODE OAUTH",
    codex_oauth: "CODEX OAUTH",
    gemini_oauth: "GEMINI OAUTH",
  };
  return labels[kind];
}
