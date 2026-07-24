import { describe, expect, it } from "vitest";
import {
  buildModelParameters,
  decomposeModelParameters,
  emptyModelParameterDraft,
} from "./modelParameters";

describe("model parameter mapping", () => {
  it("maps OpenAI Responses structured fields without losing advanced values", () => {
    const parameters = buildModelParameters("openai_responses", {
      ...emptyModelParameterDraft(),
      temperature: "0.2",
      topP: "0.9",
      maxOutputTokens: "16384",
      reasoningEffort: "xhigh",
      serviceTier: "priority",
      advanced: '{"reasoning":{"summary":"auto"},"store":false}',
    });

    expect(parameters).toEqual({
      temperature: 0.2,
      top_p: 0.9,
      max_output_tokens: 16384,
      reasoning: { summary: "auto", effort: "xhigh" },
      service_tier: "priority",
      store: false,
    });
    expect(
      decomposeModelParameters("openai_responses", parameters),
    ).toMatchObject({
      temperature: "0.2",
      maxOutputTokens: "16384",
      reasoningEffort: "xhigh",
      serviceTier: "priority",
    });
  });

  it("maps Anthropic effort into output_config", () => {
    const parameters = buildModelParameters("anthropic", {
      ...emptyModelParameterDraft(),
      maxOutputTokens: "65536",
      reasoningEffort: "max",
      serviceTier: "priority",
      advanced: '{"output_config":{"format":{"type":"json_schema"}}}',
    });

    expect(parameters).toEqual({
      max_tokens: 65536,
      output_config: {
        format: { type: "json_schema" },
        effort: "max",
      },
      service_tier: "priority",
    });
  });

  it("maps Ollama think separately from runtime options", () => {
    expect(
      buildModelParameters("ollama", {
        ...emptyModelParameterDraft(),
        temperature: "0",
        maxOutputTokens: "4096",
        reasoningEffort: "high",
      }),
    ).toEqual({
      temperature: 0,
      num_predict: 4096,
      think: "high",
    });
  });

  it("keeps Codex reasoning effort but drops unsupported sampling controls", () => {
    expect(
      buildModelParameters("codex", {
        ...emptyModelParameterDraft(),
        temperature: "0.7",
        topP: "0.8",
        maxOutputTokens: "32768",
        reasoningEffort: "xhigh",
        serviceTier: "priority",
      }),
    ).toEqual({
      reasoning: { effort: "xhigh" },
      service_tier: "priority",
    });
  });

  it("maps Gemini thinking and generation limits to native fields", () => {
    const parameters = buildModelParameters("gemini", {
      ...emptyModelParameterDraft(),
      temperature: "0.3",
      topP: "0.95",
      maxOutputTokens: "65536",
      reasoningEffort: "high",
    });

    expect(parameters).toEqual({
      temperature: 0.3,
      top_p: 0.95,
      max_output_tokens: 65536,
      thinking_config: { thinkingLevel: "high" },
    });
    expect(decomposeModelParameters("gemini", parameters)).toMatchObject({
      temperature: "0.3",
      topP: "0.95",
      maxOutputTokens: "65536",
      reasoningEffort: "high",
      serviceTier: "",
    });
  });

  it("rejects transport-owned fields in advanced JSON", () => {
    expect(() =>
      buildModelParameters("openai_compatible", {
        ...emptyModelParameterDraft(),
        advanced: '{"messages":[]}',
      }),
    ).toThrow(/managed by the Runner/);
  });

  it("rejects nested credentials in advanced JSON", () => {
    expect(() =>
      buildModelParameters("anthropic", {
        ...emptyModelParameterDraft(),
        advanced: '{"metadata":{"api_key":"do-not-send"}}',
      }),
    ).toThrow(/credentials or headers/);
  });
});
