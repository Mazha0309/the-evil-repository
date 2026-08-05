import type { BudgetOverrideEntry } from "./types";

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
