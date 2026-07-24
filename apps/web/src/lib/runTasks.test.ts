import { describe, expect, it } from "vitest";
import { orderTasks, resolveRunTask } from "./runTasks";
import type { Run, Task } from "./types";

function task(
  id: string,
  slug: string,
  name: string,
  chineseName?: string,
): Task {
  return {
    id,
    slug,
    version: "1.0.0",
    name,
    description: `${name} description`,
    category: "test",
    kind: "terminal",
    manifest: {
      localizations: chineseName
        ? {
            "zh-CN": {
              name: chineseName,
              description: `${chineseName}说明`,
            },
          }
        : undefined,
    },
    enabled: true,
    created_at: "2026-07-24T00:00:00Z",
    updated_at: "2026-07-24T00:00:00Z",
  };
}

const run = {
  task_id: "terminal-id",
  config: {},
} as Run;

describe("orderTasks", () => {
  it("puts the Terminal Repository first while preserving all other order", () => {
    const counterfeit = task(
      "counterfeit-id",
      "counterfeit-release",
      "Counterfeit",
    );
    const terminal = task("terminal-id", "terminal-repository", "Terminal");
    const third = task("third-id", "third", "Third");

    expect(
      orderTasks([counterfeit, terminal, third]).map((item) => item.id),
    ).toEqual(["terminal-id", "counterfeit-id", "third-id"]);
  });
});

describe("resolveRunTask", () => {
  it("prefers the immutable localized snapshot", () => {
    const identity = resolveRunTask(
      {
        ...run,
        config: {
          task_snapshot: {
            id: "terminal-id",
            slug: "terminal-repository",
            version: "3.0.4",
            name: "The Terminal Repository",
            description: "Snapshot description",
            localizations: {
              "zh-CN": {
                name: "终焉仓库",
                description: "快照说明",
              },
            },
          },
        },
      },
      [task("terminal-id", "terminal-repository", "Renamed")],
      true,
    );

    expect(identity).toMatchObject({
      name: "终焉仓库",
      description: "快照说明",
      version: "3.0.4",
      source: "snapshot",
    });
  });

  it("falls back to the current task for legacy runs", () => {
    const identity = resolveRunTask(
      run,
      [
        task(
          "terminal-id",
          "terminal-repository",
          "The Terminal Repository",
          "终焉仓库",
        ),
      ],
      true,
    );

    expect(identity).toMatchObject({
      name: "终焉仓库",
      source: "task",
    });
  });
});
