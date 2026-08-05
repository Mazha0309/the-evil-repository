import { describe, expect, it } from "vitest";
import { mergeBudgetOverrides, OPTIONAL_BUDGET_FIELDS } from "./budget";

describe("OPTIONAL_BUDGET_FIELDS", () => {
  it("lists the four removable optional budget fields", () => {
    expect(OPTIONAL_BUDGET_FIELDS).toEqual(
      new Set([
        "soft_provider_requests",
        "hard_provider_requests",
        "soft_total_tokens",
        "hard_total_tokens",
      ]),
    );
  });
});

describe("mergeBudgetOverrides", () => {
  it("applies overrides onto base budget", () => {
    const base = { hard_tool_calls: 2200, hard_seconds: 21600 };
    const overrides = [
      { field: "hard_tool_calls", value: 5000, reason: "r", requested_by: "u", requested_at: "t" },
    ];
    expect(mergeBudgetOverrides(base, overrides)).toEqual({ hard_tool_calls: 5000, hard_seconds: 21600 });
  });

  it("ignores unknown fields and null values", () => {
    const base = { hard_tool_calls: 2200 };
    const overrides = [
      { field: "bogus", value: 1, reason: "r", requested_by: "u", requested_at: "t" },
      { field: "hard_tool_calls", value: null, reason: "r", requested_by: "u", requested_at: "t" },
    ];
    expect(mergeBudgetOverrides(base, overrides)).toEqual({ hard_tool_calls: 2200 });
  });
});
