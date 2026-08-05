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

  it("returns an empty list for empty text", () => {
    expect(splitDiffFiles("")).toHaveLength(0);
  });

  it("returns an empty list for text without diff headers", () => {
    expect(splitDiffFiles("no header here\n+ not a real diff")).toHaveLength(0);
  });

  it("splits multiple file blocks with their own paths", () => {
    const blocks = splitDiffFiles(
      [
        "diff --git a/a.txt b/a.txt",
        "@@ -1 +1 @@",
        "+ x",
        "diff --git a/b.txt b/b.txt",
        "@@ -1 +1 @@",
        "- y",
      ].join("\n"),
    );
    expect(blocks).toHaveLength(2);
    expect(blocks[0].path).toBe("a.txt");
    expect(blocks[1].path).toBe("b.txt");
  });

  it("extracts paths containing spaces (quoted and unquoted)", () => {
    const quoted = splitDiffFiles(
      'diff --git "a/my file.txt" "b/my file.txt"',
    );
    expect(quoted).toHaveLength(1);
    expect(quoted[0].path).toBe("my file.txt");
    const plain = splitDiffFiles(
      "diff --git a/my file.txt b/my file.txt",
    );
    expect(plain[0].path).toBe("my file.txt");
  });

  it("omits the diff --git header line from block lines", () => {
    const blocks = splitDiffFiles(SAMPLE);
    expect(blocks[0].lines[0].text).toBe("--- a/README.md");
    expect(
      blocks[0].lines.some((line) => line.text.startsWith("diff --git")),
    ).toBe(false);
  });

  it("keeps ---/+++ header lines and hunk markers classified correctly", () => {
    const blocks = splitDiffFiles(SAMPLE);
    expect(blocks[0].lines.map((line) => line.type)).toEqual([
      DiffLineType.Context,
      DiffLineType.Context,
      DiffLineType.Hunk,
      DiffLineType.Removed,
      DiffLineType.Added,
    ]);
  });
});

describe("classifyLine", () => {
  it("classifies +/-/context/hunk lines", () => {
    expect(classifyLine("+ new")).toBe(DiffLineType.Added);
    expect(classifyLine("- old")).toBe(DiffLineType.Removed);
    expect(classifyLine("  ctx")).toBe(DiffLineType.Context);
    expect(classifyLine("@@ -1,1 +1,2 @@")).toBe(DiffLineType.Hunk);
  });

  it("does not classify ---/+++ file headers as removed/added", () => {
    expect(classifyLine("--- a/README.md")).toBe(DiffLineType.Context);
    expect(classifyLine("+++ b/README.md")).toBe(DiffLineType.Context);
  });

  it("classifies the no-newline marker as context", () => {
    expect(classifyLine("\\ No newline at end of file")).toBe(
      DiffLineType.Context,
    );
  });
});
