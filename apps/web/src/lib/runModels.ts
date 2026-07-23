import type {
  ModelProfile,
  ModelProvider,
  Run,
  SemanticJudgeReview,
} from "./types";

export interface RunModelIdentity {
  profileId: string | null;
  name: string | null;
  modelId: string | null;
  provider: ModelProvider | null;
  source: "snapshot" | "profile" | "semantic_review" | "unknown";
}

export function resolveRunModel(
  run: Run,
  role: "candidate" | "judge",
  profiles: ModelProfile[],
): RunModelIdentity {
  const profileId =
    role === "candidate" ? run.candidate_model_id : run.judge_model_id;
  const snapshot = objectValue(run.config[`${role}_model_snapshot`]);
  const snapshotName = textValue(snapshot.name);
  if (snapshotName) {
    return {
      profileId,
      name: snapshotName,
      modelId: textValue(snapshot.model_id),
      provider: providerValue(snapshot.provider),
      source: "snapshot",
    };
  }

  const profile = profiles.find((item) => item.id === profileId);
  if (profile) {
    return {
      profileId,
      name: profile.name,
      modelId: profile.model_id,
      provider: profile.provider,
      source: "profile",
    };
  }

  const reviewedJudge =
    role === "judge" ? semanticJudge(run.scorecard.semantic_review) : null;
  if (reviewedJudge?.name) {
    return {
      profileId,
      name: reviewedJudge.name,
      modelId: reviewedJudge.model_id ?? null,
      provider: providerValue(reviewedJudge.provider),
      source: "semantic_review",
    };
  }

  return {
    profileId,
    name: null,
    modelId: null,
    provider: null,
    source: "unknown",
  };
}

function semanticJudge(
  review: SemanticJudgeReview | undefined,
): SemanticJudgeReview["judge"] | null {
  return review?.judge ?? null;
}

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function textValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function providerValue(value: unknown): ModelProvider | null {
  return value === "openai_responses" ||
    value === "anthropic" ||
    value === "openai_compatible" ||
    value === "ollama"
    ? value
    : null;
}
