import { DiscoveredModel, ModelType } from "@/controllers/API/modelDiscovery";

export const discoveryProviders = new Set([
  "openai",
  "qwen",
  "deepseek",
  "silicon",
  "moonshot",
  "zhipu",
  "qianfan",
  "vllm",
  "xinference",
  "llamacpp",
  "MindIE",
  "ollama",
  "anthropic",
]);
export const modelTypes: ModelType[] = [
  "llm",
  "embedding",
  "rerank",
  "asr",
  "tts",
];
export function availableModelTypes(provider: string): ModelType[] {
  return ["openai", "azure_openai", "qwen", "qianfan"].includes(provider)
    ? modelTypes
    : modelTypes.filter((type) => type !== "asr" && type !== "tts");
}
export function importableModels(
  catalog: DiscoveredModel[],
  selected: Set<string>,
  types: Record<string, ModelType>,
  existing: string[],
  provider: string,
) {
  const names = new Set(existing.map((name) => name.trim()));
  const supported = availableModelTypes(provider);
  return catalog.flatMap((model) => {
    const type = types[model.model_name] || model.model_type;
    if (
      model.type_source === "unsupported" ||
      !selected.has(model.model_name) ||
      names.has(model.model_name) ||
      !type ||
      !supported.includes(type)
    )
      return [];
    names.add(model.model_name);
    return [{ ...model, model_type: type }];
  });
}
