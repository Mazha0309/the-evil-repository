import type { ScoreMetric } from "./types";

export function normalizeScoreDimensions(
  dimensions: Record<string, ScoreMetric> | null | undefined,
): Record<string, ScoreMetric> {
  if (!dimensions) return {};

  return Object.fromEntries(
    Object.entries(dimensions).flatMap(([key, rawMetric]) => {
      const metric = rawMetric as Partial<ScoreMetric> | null;
      if (!metric) return [];

      const maximum = finiteNumber(metric.maximum);
      if (maximum == null || maximum <= 0) return [];

      const rawScore = finiteNumber(metric.score) ?? 0;
      const score = Math.min(maximum, Math.max(0, rawScore));
      return [
        [
          key,
          {
            score,
            maximum,
            label: typeof metric.label === "string" ? metric.label : "",
            evidence:
              metric.evidence &&
              typeof metric.evidence === "object" &&
              !Array.isArray(metric.evidence)
                ? metric.evidence
                : {},
          },
        ],
      ];
    }),
  );
}

export function scorePercentage(metric: ScoreMetric): number {
  if (!Number.isFinite(metric.maximum) || metric.maximum <= 0) return 0;
  if (!Number.isFinite(metric.score)) return 0;
  return Math.min(100, Math.max(0, (metric.score / metric.maximum) * 100));
}

function finiteNumber(value: unknown): number | null {
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : null;
  }
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}
