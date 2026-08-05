import { useMemo, useState } from "react";
import { DiffLineType, splitDiffFiles } from "../lib/diff";
import type { DiffFileBlock } from "../lib/diff";
import { useLocale } from "../lib/i18n";
import type { RunDiff } from "../lib/types";

const PAGE_SIZE = 500;

function DiffFileBlockView({
  block,
  index,
  limit,
  onLoadMore,
}: {
  block: DiffFileBlock;
  index: number;
  limit: number;
  onLoadMore: (index: number) => void;
}) {
  const { text } = useLocale();
  const added = block.lines.filter(
    (line) => line.type === DiffLineType.Added,
  ).length;
  const removed = block.lines.filter(
    (line) => line.type === DiffLineType.Removed,
  ).length;
  const visible = block.lines.slice(0, limit);
  return (
    <details className="diff-file">
      <summary>
        <span className="diff-file__path">{block.path}</span>
        <span className="diff-file__stats">
          <span className="diff-stat diff-stat--added">+{added}</span>
          <span className="diff-stat diff-stat--removed">−{removed}</span>
        </span>
      </summary>
      <div className="diff-lines">
        {visible.map((line, i) => (
          <div
            className={`diff-line diff-line--${line.type}`}
            key={`${i}-${line.text}`}
          >
            <span className="diff-line__num">{i + 1}</span>
            <code>{line.text}</code>
          </div>
        ))}
      </div>
      {block.lines.length > limit && (
        <button
          className="button button--ghost diff-file__more"
          onClick={() => onLoadMore(index)}
        >
          {text("加载更多", "Load more")}
        </button>
      )}
    </details>
  );
}

export default function DiffViewer({ diffs }: { diffs: RunDiff[] }) {
  const { text } = useLocale();
  const [selected, setSelected] = useState(0);
  const [limits, setLimits] = useState<Record<number, number>>({});
  const active = diffs[Math.min(selected, diffs.length - 1)] ?? null;
  const blocks = useMemo(
    () => (active ? splitDiffFiles(active.diff_text) : []),
    [active],
  );
  if (!active) {
    return (
      <div className="empty-state">
        <h3>{text("无可用的改动记录", "No diffs available")}</h3>
        <p>
          {text("该仓库没有已保存的改动。", "No saved changes for this repo.")}
        </p>
      </div>
    );
  }
  return (
    <section className="panel diff-viewer">
      <div className="diff-repo-bar">
        {diffs.map((diff, index) => (
          <button
            className={
              index === Math.min(selected, diffs.length - 1)
                ? "diff-repo-bar__button active"
                : "diff-repo-bar__button"
            }
            key={diff.repo}
            onClick={() => setSelected(index)}
          >
            <span className="diff-repo-bar__name">{diff.repo}</span>
            <span className="diff-repo-bar__badges">
              <span className="diff-stat diff-stat--added">
                +{diff.added_lines}
              </span>
              <span className="diff-stat diff-stat--removed">
                −{diff.removed_lines}
              </span>
            </span>
          </button>
        ))}
      </div>
      {active.status_text && (
        <details className="diff-status">
          <summary>{text("git status", "git status")}</summary>
          <pre>{active.status_text}</pre>
        </details>
      )}
      <div className="diff-files">
        {blocks.length ? (
          blocks.map((block, index) => (
            <DiffFileBlockView
              block={block}
              index={index}
              key={`${block.path}-${index}`}
              limit={limits[index] ?? PAGE_SIZE}
              onLoadMore={(i) =>
                setLimits((prev) => ({
                  ...prev,
                  [i]: (prev[i] ?? PAGE_SIZE) + PAGE_SIZE,
                }))
              }
            />
          ))
        ) : (
          <div className="empty-state">
            <h3>{text("没有改动", "No changes")}</h3>
            <p>
              {text(
                "该仓库的 diff 为空，工作区可能是干净的。",
                "The diff is empty — the workspace may be clean.",
              )}
            </p>
          </div>
        )}
      </div>
    </section>
  );
}
