import { describe, expect, it } from "vitest";
import { bytes, compactNumber } from "./format";

describe("format helpers", () => {
  it("formats benchmark pressure values", () => {
    expect(compactNumber(5_000)).toBe("5K");
    expect(bytes(104_857_600)).toBe("100 MB");
  });
});
