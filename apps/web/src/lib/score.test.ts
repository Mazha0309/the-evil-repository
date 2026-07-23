import { describe, expect, it } from "vitest";
import { normalizeScoreDimensions, scorePercentage } from "./score";
import type { ScoreMetric } from "./types";

describe("scorecard helpers", () => {
  it("keeps valid dimensions and clamps scores to their axis range", () => {
    const dimensions = normalizeScoreDimensions({
      functional_correctness: {
        score: 240,
        maximum: 200,
        label: "Functional correctness",
      },
      security: {
        score: -10,
        maximum: 120,
        label: "Security",
      },
    });

    expect(dimensions.functional_correctness).toMatchObject({
      score: 200,
      maximum: 200,
    });
    expect(dimensions.security).toMatchObject({ score: 0, maximum: 120 });
  });

  it("drops invalid radar axes instead of passing NaN or zero maxima to ECharts", () => {
    const malformed = {
      valid: { score: "40", maximum: "50", label: null },
      zero: { score: 0, maximum: 0, label: "Zero" },
      infinite: {
        score: Number.POSITIVE_INFINITY,
        maximum: 100,
        label: "Infinite",
      },
    } as unknown as Record<string, ScoreMetric>;

    expect(normalizeScoreDimensions(malformed)).toEqual({
      valid: { score: 40, maximum: 50, label: "", evidence: {} },
      infinite: { score: 0, maximum: 100, label: "Infinite", evidence: {} },
    });
  });

  it("always returns a bounded CSS percentage", () => {
    expect(
      scorePercentage({ score: 75, maximum: 50, label: "Over maximum" }),
    ).toBe(100);
    expect(
      scorePercentage({ score: 20, maximum: 0, label: "Bad maximum" }),
    ).toBe(0);
  });
});
