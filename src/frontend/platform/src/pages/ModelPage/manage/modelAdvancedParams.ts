import { ModelType } from "@/controllers/API/modelDiscovery";
import {
  getAdvancedParamsTemplate,
  templateToJsonString,
} from "@/util/advancedParamsTemplates";

export interface ModelItemConfig {
  voice?: string;
  enable_web_search?: boolean;
  max_tokens?: number;
  user_kwargs?: string;
}

export function parseAdvancedParams(input: string): Record<string, unknown> {
  if (!input.trim()) return {};
  const parsed: unknown = JSON.parse(input);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("Advanced parameters must be a JSON object.");
  }
  return parsed as Record<string, unknown>;
}

export function advancedParamsText(
  config: ModelItemConfig | undefined,
  provider: string,
  modelType: ModelType,
): string {
  const input = config?.user_kwargs || "";
  if (modelType !== "llm" || !config?.max_tokens) return input;
  try {
    // Preserve the effective legacy value, which currently takes priority.
    return JSON.stringify(
      {
        ...parseAdvancedParams(input),
        [provider === "ollama" ? "num_ctx" : "max_tokens"]: config.max_tokens,
      },
      null,
      2,
    );
  } catch {
    // Keep malformed saved input visible so the administrator can correct it.
    return input;
  }
}

export function withAdvancedParams(
  config: ModelItemConfig | undefined,
  input: string,
  modelType: ModelType,
): ModelItemConfig {
  parseAdvancedParams(input);
  const next = { ...config, user_kwargs: input.trim() };
  if (modelType === "llm") delete next.max_tokens;
  return next;
}

export function advancedParamsPlaceholder(
  provider: string,
  modelType: ModelType,
): string {
  const template = {
    ...getAdvancedParamsTemplate(provider, modelType as "llm" | "embedding"),
  };
  if (modelType === "llm") {
    const key = provider === "ollama" ? "num_ctx" : "max_tokens";
    template[key] = provider === "ollama" ? 2048 : 1024;
  }
  return templateToJsonString(template);
}
