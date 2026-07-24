export type RunStatus =
  | "queued"
  | "preparing"
  | "running"
  | "scoring"
  | "completed"
  | "failed"
  | "cancelled";

export type UserRole = "admin" | "user";

export interface AuthConfig {
  setup_required: boolean;
  registration_enabled: boolean;
  setup_token_required: boolean;
  version: string;
}

export interface UserAccount {
  id: string;
  username: string;
  role: UserRole;
  enabled: boolean;
  last_login_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface AuthResponse {
  user: UserAccount;
  csrf_token: string;
  expires_at: string;
}

export interface AccountSession {
  id: string;
  expires_at: string;
  user_agent: string | null;
  ip_address: string | null;
  created_at: string;
  last_seen_at: string;
  current: boolean;
}

export interface PlatformSettings {
  registration_enabled: boolean;
  runner_concurrency: number;
  updated_by: string | null;
  updated_at: string;
}

export interface AdminSummary {
  users: number;
  enabled_users: number;
  admins: number;
  models: number;
  total_runs: number;
  active_runs: number;
}

export interface ServerMonitor {
  observed_at: string;
  api: Record<string, number | string | boolean | null>;
  runner: Record<string, number | string | boolean | null>;
  database: Record<string, number | string | boolean | null>;
  queue: {
    counts: Record<RunStatus, number>;
    active: number;
    queued: number;
  };
}

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
      soft_provider_requests?: number;
      hard_provider_requests?: number;
      soft_total_tokens?: number | null;
      hard_total_tokens?: number | null;
    };
    context_pressure?: {
      target_files: number;
      target_git_commits: number;
      target_mirror_bytes: number;
    };
    scoring?: Record<string, number>;
    repositories?: Array<Record<string, unknown>>;
    tools?: string[];
    completion?: CompletionSpec;
    incident?: IncidentSpec;
    release?: ReleaseSpec;
    components?: {
      database?: Record<string, string>;
      failures?: string[];
      mirror?: string;
    };
    localizations?: Record<
      string,
      {
        name?: string;
        description?: string;
      }
    >;
  };
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface BenchmarkSuite {
  schema_version: number;
  slug: string;
  version: string;
  name: string;
  description: string;
  families: Array<{
    id: string;
    name: string;
    description: string;
    capabilities: string[];
    status: "active" | "planned" | "retired";
  }>;
  scenarios: Array<{
    slug: string;
    version: string;
    family: string;
    split: "development" | "validation" | "held_out";
    instances: number;
    weight: number;
  }>;
  readiness: {
    active_families: number;
    held_out_families: number;
    scenario_references: number;
    required_active_families: number;
    required_held_out_families: number;
    required_scenarios: number;
    leaderboard_eligible: boolean;
  };
  localizations?: Record<string, { name?: string; description?: string }>;
}

export interface CompletionSpec {
  min_tool_calls?: number;
  min_hypotheses?: number;
  min_rejected_hypotheses?: number;
  min_evidence?: number;
  required_evidence_sources?: string[];
  required_actions?: string[];
  required_artifacts?: Record<string, number>;
}

export interface IncidentSpec {
  enabled?: boolean;
  logical_tick_seconds?: number;
  horizon_ticks?: number;
  min_logical_ticks?: number;
  min_unique_observations?: number;
  min_services_observed?: number;
  phase_observations?: Record<string, number>;
  required_decisions?: string[];
  require_snapshot_before_risky_action?: boolean;
  required_verification_modes?: string[];
  required_successful_verification_modes?: string[];
  required_verification_sequence?: string[];
}

export interface ReleaseSpec {
  enabled?: boolean;
  logical_tick_seconds?: number;
  horizon_ticks?: number;
  min_logical_ticks?: number;
  min_unique_observations?: number;
  required_decisions?: string[];
  require_snapshot_before_irreversible?: boolean;
  require_containment?: boolean;
  required_verification_modes?: string[];
  required_successful_verification_modes?: string[];
  required_verification_sequence?: string[];
}

export interface ModelProfile {
  id: string;
  name: string;
  provider: ModelProvider;
  base_url: string;
  model_id: string;
  has_api_key: boolean;
  credential_id: string | null;
  credential_name: string | null;
  credential_kind: CredentialKind | null;
  credential_status: CredentialStatus | null;
  native_tools: boolean;
  parameters: Record<string, unknown>;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export type ModelProvider =
  | "openai_responses"
  | "anthropic"
  | "openai_compatible"
  | "ollama"
  | "codex"
  | "gemini";

export type CredentialKind =
  | "api_key"
  | "codex_oauth"
  | "gemini_oauth";

export type CredentialStatus =
  | "unchecked"
  | "ready"
  | "expired"
  | "needs_reauth"
  | "error";

export interface ProviderCredential {
  id: string;
  name: string;
  kind: CredentialKind;
  account_hint: string | null;
  status: CredentialStatus;
  expires_at: string | null;
  last_refreshed_at: string | null;
  last_validated_at: string | null;
  last_error_code: string | null;
  model_count: number;
  created_at: string;
  updated_at: string;
}

export interface OAuthDeviceStart {
  expires_at: string;
  flow_token: string;
  interval: number;
  user_code: string;
  verification_uri: string;
}

export interface OAuthDevicePollResult {
  state: "pending" | "complete";
  credential: ProviderCredential | null;
}

export interface ScoreMetric {
  score: number;
  maximum: number;
  label: string;
  evidence?: Record<string, unknown>;
}

export interface SemanticJudgeCriterion {
  score: number;
  maximum: number;
  rationale: string;
  evidence_refs: string[];
  valid_evidence_refs: string[];
  invalid_evidence_refs: string[];
}

export interface SemanticJudgeReview {
  status: "not_requested" | "completed" | "failed";
  schema_version: string;
  score: number | null;
  maximum: number;
  affects_primary_score: false;
  rating?: "excellent" | "strong" | "mixed" | "weak";
  confidence?: number;
  summary?: string;
  criteria?: Record<string, SemanticJudgeCriterion>;
  strengths?: string[];
  weaknesses?: string[];
  disputed_claims?: Array<{
    claim: string;
    reason: string;
    evidence_refs: string[];
    valid_evidence_refs: string[];
    invalid_evidence_refs: string[];
  }>;
  reliability?: {
    level: "high" | "medium" | "low";
    grounded_criteria: number;
    required_criteria: number;
    valid_reference_count: number;
    invalid_references: string[];
    injection_canaries: string[];
  };
  judge?: {
    profile_id?: string | null;
    name?: string;
    provider?: ModelProvider;
    model_id?: string;
  };
  prompt_sha256?: string;
  attempts?: number;
  usage?: {
    input_tokens: number;
    output_tokens: number;
  };
  duration_ms?: number;
  errors?: string[];
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
    deductions?: Array<{
      code: string;
      points: number;
      count: number;
      detail: string;
    }>;
    behavior_profile?: Record<string, number>;
    error_profile?: Record<string, number>;
    semantic_review?: SemanticJudgeReview;
    resources?: Record<string, unknown> & {
      hard_limits_crossed?: string[];
    };
    agent_graph?: {
      schema_version: number;
      execution_mode: "single_agent" | "multi_agent";
      agent_count: number;
      edge_count: number;
    };
    completion?: {
      met: boolean;
      tool_calls: number;
      substantive_tool_calls?: number;
    };
    outcome?: {
      status:
        | "verified_success"
        | "evaluated_incomplete"
        | "budget_exhausted";
      censored: boolean;
      hard_budget_reasons: string[];
      runtime_calibration_eligible: boolean;
      calibration_exclusions: string[];
      minimum_success_score: number;
    };
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

export interface RunArtifact {
  id: string;
  run_id: string;
  name: string;
  media_type: string;
  sha256: string;
  size: number;
  metadata_json: {
    kind?: "scenario-run-archive" | "failure-checkpoint" | string;
    resumable?: boolean;
    replayable?: boolean;
  };
  created_at: string;
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
