import type { ModelProvider } from "./types";

export interface ModelParameterDraft {
  temperature: string;
  topP: string;
  maxOutputTokens: string;
  reasoningEffort: string;
  serviceTier: string;
  advanced: string;
}

export interface ParameterOption {
  value: string;
  label: string;
}

const RESERVED_KEYS = new Set([
  "model",
  "messages",
  "input",
  "system",
  "instructions",
  "tools",
  "tool_choice",
  "stream",
]);
const SENSITIVE_KEYS = new Set([
  "api_key",
  "apikey",
  "authorization",
  "headers",
  "x_api_key",
  "x-api-key",
]);

export function emptyModelParameterDraft(): ModelParameterDraft {
  return {
    temperature: "",
    topP: "",
    maxOutputTokens: "",
    reasoningEffort: "",
    serviceTier: "",
    advanced: "{}",
  };
}

export function decomposeModelParameters(
  provider: ModelProvider,
  parameters: Record<string, unknown>,
): ModelParameterDraft {
  const rest = cloneObject(parameters);
  const draft = emptyModelParameterDraft();
  draft.temperature = takeNumber(rest, "temperature");
  draft.topP = takeNumber(rest, "top_p");
  draft.maxOutputTokens = takeNumber(rest, maxTokensKey(provider));

  if (provider === "openai_responses" || provider === "codex") {
    draft.reasoningEffort = takeNestedString(rest, "reasoning", "effort");
  } else if (provider === "anthropic") {
    draft.reasoningEffort = takeNestedString(rest, "output_config", "effort");
  } else if (provider === "gemini") {
    draft.reasoningEffort = takeNestedString(
      rest,
      "thinking_config",
      "thinkingLevel",
    );
  } else if (provider === "openai_compatible") {
    draft.reasoningEffort = takeString(rest, "reasoning_effort");
  } else {
    const think = rest.think;
    if (typeof think === "boolean") {
      draft.reasoningEffort = think ? "on" : "off";
      delete rest.think;
    } else if (typeof think === "string") {
      draft.reasoningEffort = think;
      delete rest.think;
    }
  }

  if (provider !== "ollama" && provider !== "gemini") {
    draft.serviceTier = takeString(rest, "service_tier");
  }
  draft.advanced = JSON.stringify(rest, null, 2);
  return draft;
}

export function buildModelParameters(
  provider: ModelProvider,
  draft: ModelParameterDraft,
): Record<string, unknown> {
  const parameters = parseAdvancedParameters(draft.advanced);
  assertSafeParameterKeys(parameters);
  for (const key of Object.keys(parameters)) {
    if (RESERVED_KEYS.has(key)) {
      throw new Error(`"${key}" is managed by the Runner`);
    }
  }

  if (provider !== "codex") {
    assignNumber(parameters, "temperature", draft.temperature, 0, 2);
    assignNumber(parameters, "top_p", draft.topP, 0, 1);
    assignInteger(parameters, maxTokensKey(provider), draft.maxOutputTokens, 1);
  }

  if (draft.reasoningEffort) {
    if (provider === "openai_responses" || provider === "codex") {
      parameters.reasoning = mergeNested(parameters.reasoning, {
        effort: draft.reasoningEffort,
      });
    } else if (provider === "anthropic") {
      parameters.output_config = mergeNested(parameters.output_config, {
        effort: draft.reasoningEffort,
      });
    } else if (provider === "openai_compatible") {
      parameters.reasoning_effort = draft.reasoningEffort;
    } else if (provider === "gemini") {
      parameters.thinking_config = mergeNested(parameters.thinking_config, {
        thinkingLevel: draft.reasoningEffort,
      });
    } else {
      parameters.think =
        draft.reasoningEffort === "on"
          ? true
          : draft.reasoningEffort === "off"
            ? false
            : draft.reasoningEffort;
    }
  }

  if (
    draft.serviceTier &&
    provider !== "ollama" &&
    provider !== "gemini"
  ) {
    parameters.service_tier = draft.serviceTier;
  }
  return parameters;
}

export function modelParameterSummary(
  provider: ModelProvider,
  parameters: Record<string, unknown>,
): string[] {
  const draft = decomposeModelParameters(provider, parameters);
  const result: string[] = [];
  if (draft.reasoningEffort) result.push(`effort ${draft.reasoningEffort}`);
  if (draft.temperature) result.push(`temperature ${draft.temperature}`);
  if (draft.topP) result.push(`top_p ${draft.topP}`);
  if (draft.maxOutputTokens) {
    result.push(`max output ${draft.maxOutputTokens}`);
  }
  if (draft.serviceTier) result.push(`tier ${draft.serviceTier}`);
  const customCount = Object.keys(
    parseAdvancedParameters(draft.advanced),
  ).length;
  if (customCount) result.push(`advanced +${customCount}`);
  return result;
}

export function reasoningOptions(provider: ModelProvider): ParameterOption[] {
  if (provider === "anthropic") {
    return ["low", "medium", "high", "xhigh", "max"].map(option);
  }
  if (provider === "ollama") {
    return ["off", "on", "low", "medium", "high"].map(option);
  }
  if (provider === "gemini") {
    return ["minimal", "low", "medium", "high"].map(option);
  }
  return ["none", "minimal", "low", "medium", "high", "xhigh", "max"].map(
    option,
  );
}

export function serviceTierOptions(provider: ModelProvider): ParameterOption[] {
  if (provider === "anthropic") {
    return ["standard", "priority"].map(option);
  }
  if (provider === "ollama" || provider === "gemini") return [];
  return ["auto", "default", "flex", "priority"].map(option);
}

export function parameterFieldNames(provider: ModelProvider) {
  const effort =
    provider === "openai_responses" || provider === "codex"
      ? "reasoning.effort"
      : provider === "anthropic"
        ? "output_config.effort"
        : provider === "gemini"
          ? "thinking_config.thinkingLevel"
        : provider === "openai_compatible"
          ? "reasoning_effort"
          : "think";
  return {
    effort,
    maxOutputTokens: maxTokensKey(provider),
  };
}

function parseAdvancedParameters(value: string): Record<string, unknown> {
  let parsed: unknown;
  try {
    parsed = JSON.parse(value || "{}");
  } catch {
    throw new Error("Advanced parameters must be valid JSON");
  }
  if (!isObject(parsed)) {
    throw new Error("Advanced parameters must be a JSON object");
  }
  return parsed;
}

function assertSafeParameterKeys(value: unknown): void {
  if (Array.isArray(value)) {
    value.forEach(assertSafeParameterKeys);
    return;
  }
  if (!isObject(value)) return;
  for (const [key, nested] of Object.entries(value)) {
    const normalized = key.trim().toLowerCase().replaceAll(" ", "_");
    if (SENSITIVE_KEYS.has(normalized)) {
      throw new Error(`"${key}" must not contain credentials or headers`);
    }
    assertSafeParameterKeys(nested);
  }
}

function maxTokensKey(provider: ModelProvider): string {
  if (
    provider === "openai_responses" ||
    provider === "codex" ||
    provider === "gemini"
  ) {
    return "max_output_tokens";
  }
  if (provider === "anthropic") return "max_tokens";
  if (provider === "ollama") return "num_predict";
  return "max_completion_tokens";
}

function assignNumber(
  target: Record<string, unknown>,
  key: string,
  raw: string,
  minimum: number,
  maximum: number,
) {
  if (!raw) return;
  const value = Number(raw);
  if (!Number.isFinite(value) || value < minimum || value > maximum) {
    throw new Error(`${key} must be between ${minimum} and ${maximum}`);
  }
  target[key] = value;
}

function assignInteger(
  target: Record<string, unknown>,
  key: string,
  raw: string,
  minimum: number,
) {
  if (!raw) return;
  const value = Number(raw);
  if (!Number.isInteger(value) || value < minimum) {
    throw new Error(`${key} must be an integer of at least ${minimum}`);
  }
  target[key] = value;
}

function mergeNested(
  value: unknown,
  addition: Record<string, unknown>,
): Record<string, unknown> {
  return { ...(isObject(value) ? value : {}), ...addition };
}

function takeNumber(target: Record<string, unknown>, key: string): string {
  const value = target[key];
  if (typeof value !== "number") return "";
  delete target[key];
  return String(value);
}

function takeString(target: Record<string, unknown>, key: string): string {
  const value = target[key];
  if (typeof value !== "string") return "";
  delete target[key];
  return value;
}

function takeNestedString(
  target: Record<string, unknown>,
  parent: string,
  child: string,
): string {
  const value = target[parent];
  if (!isObject(value) || typeof value[child] !== "string") return "";
  const result = value[child] as string;
  const remaining = { ...value };
  delete remaining[child];
  if (Object.keys(remaining).length) target[parent] = remaining;
  else delete target[parent];
  return result;
}

function cloneObject(value: Record<string, unknown>): Record<string, unknown> {
  return JSON.parse(JSON.stringify(value)) as Record<string, unknown>;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function option(value: string): ParameterOption {
  return { value, label: value };
}
