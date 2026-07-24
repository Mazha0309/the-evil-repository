import type { Run, Task } from "./types";

export interface RunTaskIdentity {
  id: string | null;
  slug: string | null;
  version: string | null;
  name: string | null;
  description: string | null;
  source: "snapshot" | "task" | "unknown";
}

const PRIORITY_SCENARIO_SLUG = "terminal-repository";

export function orderTasks(tasks: Task[]): Task[] {
  return tasks
    .map((task, index) => ({ task, index }))
    .sort((left, right) => {
      const leftPriority = left.task.slug === PRIORITY_SCENARIO_SLUG ? 0 : 1;
      const rightPriority = right.task.slug === PRIORITY_SCENARIO_SLUG ? 0 : 1;
      return leftPriority - rightPriority || left.index - right.index;
    })
    .map(({ task }) => task);
}

export function resolveRunTask(
  run: Run,
  tasks: Task[],
  isChinese: boolean,
): RunTaskIdentity {
  const snapshot = objectValue(run.config.task_snapshot);
  const snapshotName = localizedSnapshotValue(snapshot, "name", isChinese);
  if (snapshotName) {
    return {
      id: textValue(snapshot.id) ?? run.task_id,
      slug: textValue(snapshot.slug),
      version: textValue(snapshot.version),
      name: snapshotName,
      description: localizedSnapshotValue(snapshot, "description", isChinese),
      source: "snapshot",
    };
  }

  const task = tasks.find((item) => item.id === run.task_id);
  if (task) {
    const localized = isChinese
      ? task.manifest.localizations?.["zh-CN"]
      : undefined;
    return {
      id: task.id,
      slug: task.slug,
      version: task.version,
      name: localized?.name ?? task.name,
      description: localized?.description ?? task.description,
      source: "task",
    };
  }

  return {
    id: run.task_id,
    slug: null,
    version: null,
    name: null,
    description: null,
    source: "unknown",
  };
}

function localizedSnapshotValue(
  snapshot: Record<string, unknown>,
  key: "name" | "description",
  isChinese: boolean,
): string | null {
  if (isChinese) {
    const localizations = objectValue(snapshot.localizations);
    const chinese = objectValue(localizations["zh-CN"]);
    const localized = textValue(chinese[key]);
    if (localized) return localized;
  }
  return textValue(snapshot[key]);
}

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function textValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}
