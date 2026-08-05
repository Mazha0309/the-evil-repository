import { describe, expect, it } from "vitest";
import { splitDiffFiles, DiffLineType, classifyLine } from "../lib/diff";

const SAMPLE = [
  "diff --git a/README.md b/README.md",
  "--- a/README.md",
  "+++ b/README.md",
  "@@ -1,1 +1,2 @@",
  "- old",
  "+ new",
].join("\n");

describe("splitDiffFiles", () => {
  it("splits unified diff into per-file blocks", () => {
    const blocks = splitDiffFiles(SAMPLE);
    expect(blocks).toHaveLength(1);
    expect(blocks[0].path).toBe("README.md");
  });
});

describe("classifyLine", () => {
  it("classifies +/-/context/hunk lines", () => {
    expect(classifyLine("+ new")).toBe(DiffLineType.Added);
    expect(classifyLine("- old")).toBe(DiffLineType.Removed);
    expect(classifyLine("  ctx")).toBe(DiffLineType.Context);
    expect(classifyLine("@@ -1,1 +1,2 @@")).toBe(DiffLineType.Hunk);
  });
});
