export type RunStatus =
  | "queued"
  | "preparing"
  | "running"
  | "scoring"
  | "completed"
  | "failed"
  | "cancelled";

export interface DashboardSummary {
  tasks: number;
  models: number;
  total_runs: number;
  active_runs: number;
  completed_runs: number;
  average_score: number | null;
  docker_ready: boolean;
  runner_enabled: boolean;
}

export interface Task {
  id: string;
  slug: string;
  version: string;
  name: string;
  description: string;
  category: string;
  kind: string;
  manifest: {
    budget?: {
      soft_seconds: number;
      hard_seconds: number;
      soft_tool_calls: number;
      hard_tool_calls: number;
    };
    context_pressure?: {
      target_files: number;
      target_git_commits: number;
      target_mirror_bytes: number;
    };
    scoring?: Record<string, number>;
    repositories?: Array<Record<string, unknown>>;
    tools?: string[];
  };
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface ModelProfile {
  id: string;
  name: string;
  provider: "openai_compatible" | "ollama";
  base_url: string;
  model_id: string;
  has_api_key: boolean;
  native_tools: boolean;
  parameters: Record<string, unknown>;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface ScoreMetric {
  score: number;
  maximum: number;
  label: string;
  evidence?: Record<string, unknown>;
}

export interface Run {
  id: string;
  task_id: string;
  candidate_model_id: string;
  judge_model_id: string | null;
  status: RunStatus;
  stage: string;
  score: number | null;
  scorecard: {
    maximum?: number;
    dimensions?: Record<string, ScoreMetric>;
    caps?: Array<{ reason: string; max: number }>;
  };
  config: Record<string, unknown>;
  tool_calls: number;
  input_tokens: number;
  output_tokens: number;
  estimated_cost: number;
  error: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface RunEvent {
  id: number;
  run_id: string;
  sequence: number;
  kind: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface Hypothesis {
  id: string;
  run_id: string;
  key: string;
  statement: string;
  status: "proposed" | "testing" | "supported" | "rejected" | "confirmed";
  confidence: number;
  next_action: string | null;
  created_at: string;
  updated_at: string;
}

export interface HypothesisRevision {
  id: number;
  hypothesis_id: string;
  sequence: number;
  statement: string;
  status: Hypothesis["status"];
  confidence: number;
  next_action: string | null;
  reason: string | null;
  created_at: string;
}

export interface Evidence {
  id: string;
  run_id: string;
  key: string;
  source_type: string;
  source_ref: string;
  summary: string;
  trust: number;
  content_hash: string | null;
  created_at: string;
}

export interface EvidenceEdge {
  id: string;
  run_id: string;
  source_type: string;
  source_key: string;
  target_type: string;
  target_key: string;
  relation: string;
  weight: number;
  explanation: string | null;
  created_at: string;
}

export interface InvestigationGraph {
  hypotheses: Hypothesis[];
  revisions: HypothesisRevision[];
  evidence: Evidence[];
  edges: EvidenceEdge[];
}
