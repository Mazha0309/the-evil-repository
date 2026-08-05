export enum DiffLineType {
  Added = "added",
  Removed = "removed",
  Context = "context",
  Hunk = "hunk",
}

export interface DiffFileBlock {
  path: string;
  lines: { type: DiffLineType; text: string }[];
}

export function classifyLine(line: string): DiffLineType {
  if (line.startsWith("@@")) return DiffLineType.Hunk;
  if (line.startsWith("+") && !line.startsWith("+++")) return DiffLineType.Added;
  if (line.startsWith("-") && !line.startsWith("---"))
    return DiffLineType.Removed;
  return DiffLineType.Context;
}

export function splitDiffFiles(diffText: string): DiffFileBlock[] {
  const blocks: DiffFileBlock[] = [];
  let current: DiffFileBlock | null = null;
  for (const raw of diffText.split("\n")) {
    if (raw.startsWith("diff --git ")) {
      if (current) blocks.push(current);
      const match = /diff --git "?a\/(.+?) "?b\//.exec(raw);
      current = {
        path: (match?.[1] ?? raw.replace("diff --git ", "")).replace(
          /^"|"$/g,
          "",
        ),
        lines: [],
      };
    } else if (current) {
      current.lines.push({ type: classifyLine(raw), text: raw });
    }
  }
  if (current) blocks.push(current);
  return blocks;
}
