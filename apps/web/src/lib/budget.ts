import type { BudgetOverrideEntry } from "./types";

export const OPTIONAL_BUDGET_FIELDS: ReadonlySet<string> = new Set([
  "soft_provider_requests",
  "hard_provider_requests",
  "soft_total_tokens",
  "hard_total_tokens",
]);

export function mergeBudgetOverrides(
  base: Record<string, number | null>,
  overrides: BudgetOverrideEntry[],
): Record<string, number | null> {
  const merged = { ...base };
  for (const entry of overrides) {
    if (entry.field in merged && entry.value !== null) {
      merged[entry.field] = entry.value;
    }
  }
  return merged;
}
