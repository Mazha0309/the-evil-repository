import type {
  DashboardSummary,
  InvestigationGraph,
  ModelProfile,
  Run,
  RunEvent,
  Task,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8080/api/v1";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `${response.status} ${response.statusText}`);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  summary: () => request<DashboardSummary>("/dashboard/summary"),
  tasks: () => request<Task[]>("/tasks"),
  models: () => request<ModelProfile[]>("/models"),
  runs: () => request<Run[]>("/runs"),
  run: (id: string) => request<Run>(`/runs/${id}`),
  events: (id: string) => request<RunEvent[]>(`/runs/${id}/events`),
  graph: (id: string) => request<InvestigationGraph>(`/runs/${id}/graph`),
  createModel: (payload: Record<string, unknown>) =>
    request<ModelProfile>("/models", { method: "POST", body: JSON.stringify(payload) }),
  deleteModel: (id: string) => request<void>(`/models/${id}`, { method: "DELETE" }),
  createRun: (payload: Record<string, unknown>) =>
    request<Run>("/runs", { method: "POST", body: JSON.stringify(payload) }),
  cancelRun: (id: string) => request<Run>(`/runs/${id}/cancel`, { method: "POST" }),
  reportUrl: (id: string) => `${API_BASE}/reports/${id}`,
};
