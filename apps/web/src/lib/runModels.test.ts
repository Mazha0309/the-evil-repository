import { describe, expect, it } from "vitest";
import { resolveRunModel } from "./runModels";
import type { ModelProfile, Run } from "./types";

const run = {
  candidate_model_id: "candidate-id",
  judge_model_id: "judge-id",
  config: {},
  scorecard: {},
} as Run;

const profile = {
  id: "candidate-id",
  name: "Current profile name",
  provider: "anthropic",
  model_id: "claude-current",
} as ModelProfile;

describe("resolveRunModel", () => {
  it("prefers the immutable run snapshot over a renamed profile", () => {
    const identity = resolveRunModel(
      {
        ...run,
        config: {
          candidate_model_snapshot: {
            name: "Claude at run time",
            provider: "anthropic",
            model_id: "claude-snapshot",
          },
        },
      },
      "candidate",
      [profile],
    );

    expect(identity).toMatchObject({
      name: "Claude at run time",
      modelId: "claude-snapshot",
      provider: "anthropic",
      source: "snapshot",
    });
  });

  it("uses the current profile for historical runs without snapshots", () => {
    expect(resolveRunModel(run, "candidate", [profile])).toMatchObject({
      name: "Current profile name",
      modelId: "claude-current",
      source: "profile",
    });
  });

  it("recovers a historical judge name from the semantic review", () => {
    const identity = resolveRunModel(
      {
        ...run,
        scorecard: {
          semantic_review: {
            status: "completed",
            schema_version: "1",
            score: 82,
            maximum: 100,
            affects_primary_score: false,
            judge: {
              name: "Review model",
              provider: "openai_responses",
              model_id: "gpt-review",
            },
          },
        },
      },
      "judge",
      [],
    );

    expect(identity).toMatchObject({
      name: "Review model",
      modelId: "gpt-review",
      source: "semantic_review",
    });
  });
});
