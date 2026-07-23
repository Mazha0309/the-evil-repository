import type {
  AccountSession,
  AdminSummary,
  AuthConfig,
  AuthResponse,
  DashboardSummary,
  InvestigationGraph,
  ModelProfile,
  BenchmarkSuite,
  PlatformSettings,
  Run,
  RunEvent,
  ServerMonitor,
  Task,
  UserAccount,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "/api/v1";
let csrfToken = "";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method ?? "GET").toUpperCase();
  const mutating = !["GET", "HEAD", "OPTIONS"].includes(method);
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(mutating && csrfToken ? { "X-CSRF-Token": csrfToken } : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    const body = await response.text();
    let message = body;
    try {
      const parsed = JSON.parse(body) as { detail?: string };
      message = parsed.detail ?? body;
    } catch {
      // Keep the plain response body.
    }
    throw new ApiError(
      response.status,
      message || `${response.status} ${response.statusText}`,
    );
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

async function authenticate(
  path: string,
  payload?: Record<string, unknown>,
): Promise<AuthResponse> {
  const result = await request<AuthResponse>(path, {
    method: "POST",
    body: payload ? JSON.stringify(payload) : undefined,
  });
  csrfToken = result.csrf_token;
  return result;
}

export const api = {
  authConfig: () => request<AuthConfig>("/auth/config"),
  me: async () => {
    const result = await request<AuthResponse>("/auth/me");
    csrfToken = result.csrf_token;
    return result;
  },
  setup: (payload: Record<string, unknown>) =>
    authenticate("/auth/setup", payload),
  register: (payload: Record<string, unknown>) =>
    authenticate("/auth/register", payload),
  login: (payload: Record<string, unknown>) =>
    authenticate("/auth/login", payload),
  logout: async () => {
    await request<void>("/auth/logout", { method: "POST" });
    csrfToken = "";
  },
  updateAccount: (payload: Record<string, unknown>) =>
    request<UserAccount>("/auth/me", {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  sessions: () => request<AccountSession[]>("/auth/sessions"),
  revokeSession: (id: string) =>
    request<void>(`/auth/sessions/${id}`, { method: "DELETE" }),
  summary: () => request<DashboardSummary>("/dashboard/summary"),
  tasks: () => request<Task[]>("/tasks"),
  suites: () => request<BenchmarkSuite[]>("/suites"),
  taskExportUrl: (id: string) => `${API_BASE}/tasks/${id}/export`,
  models: () => request<ModelProfile[]>("/models"),
  runs: () => request<Run[]>("/runs"),
  run: (id: string) => request<Run>(`/runs/${id}`),
  events: (id: string, after = 0) =>
    request<RunEvent[]>(`/runs/${id}/events?after=${after}`),
  graph: (id: string) => request<InvestigationGraph>(`/runs/${id}/graph`),
  createModel: (payload: Record<string, unknown>) =>
    request<ModelProfile>("/models", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateModel: (id: string, payload: Record<string, unknown>) =>
    request<ModelProfile>(`/models/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  deleteModel: (id: string) =>
    request<void>(`/models/${id}`, { method: "DELETE" }),
  createRun: (payload: Record<string, unknown>) =>
    request<Run>("/runs", { method: "POST", body: JSON.stringify(payload) }),
  cancelRun: (id: string) =>
    request<Run>(`/runs/${id}/cancel`, { method: "POST" }),
  deleteRun: (id: string) =>
    request<void>(`/runs/${id}`, { method: "DELETE" }),
  pauseRun: (id: string) =>
    request<Run>(`/runs/${id}/pause`, { method: "POST" }),
  resumeRun: (id: string) =>
    request<Run>(`/runs/${id}/resume`, { method: "POST" }),
  reportUrl: (id: string) => `${API_BASE}/reports/${id}`,
  adminSummary: () => request<AdminSummary>("/admin/summary"),
  adminUsers: () => request<UserAccount[]>("/admin/users"),
  createUser: (payload: Record<string, unknown>) =>
    request<UserAccount>("/admin/users", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateUser: (id: string, payload: Record<string, unknown>) =>
    request<UserAccount>(`/admin/users/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  revokeUserSessions: (id: string) =>
    request<void>(`/admin/users/${id}/revoke-sessions`, { method: "POST" }),
  platformSettings: () => request<PlatformSettings>("/admin/settings"),
  updatePlatformSettings: (payload: Record<string, unknown>) =>
    request<PlatformSettings>("/admin/settings", {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  serverMonitor: () => request<ServerMonitor>("/admin/monitor"),
};
