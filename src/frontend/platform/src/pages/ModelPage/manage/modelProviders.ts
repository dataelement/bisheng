export interface ModelProviderEntry {
  name: string;
  value: string;
  labelKey?: string;
  /** Suffix under model.providerGroups. Ungrouped entries stay above the groups. */
  group?: "cloud" | "local";
}

// Ungrouped entries stay on top; groups follow in first-appearance order.
export const modelProvider: ModelProviderEntry[] = [
  {
    name: "",
    labelKey: "model.providerNames.openaiCompatible",
    value: "openai_compatible",
  },
  { name: "OpenAI", value: "openai", group: "cloud" },
  { name: "Azure OpenAI", value: "azure_openai", group: "cloud" },
  { name: "", labelKey: "model.providerNames.qwen", value: "qwen", group: "cloud" },
  { name: "DeepSeek", value: "deepseek", group: "cloud" },
  { name: "", labelKey: "model.providerNames.silicon", value: "silicon", group: "cloud" },
  { name: "", labelKey: "model.providerNames.volcengine", value: "volcengine", group: "cloud" },
  { name: "", labelKey: "model.providerNames.zhipu", value: "zhipu", group: "cloud" },
  { name: "", labelKey: "model.providerNames.spark", value: "spark", group: "cloud" },
  { name: "", labelKey: "model.providerNames.tencent", value: "tencent", group: "cloud" },
  { name: "", labelKey: "model.providerNames.moonshot", value: "moonshot", group: "cloud" },
  { name: "", labelKey: "model.providerNames.qianfan", value: "qianfan", group: "cloud" },
  { name: "Minimax", value: "minimax", group: "cloud" },
  { name: "Anthropic", value: "anthropic", group: "cloud" },
  { name: "Ollama", value: "ollama", group: "local" },
  { name: "xinference", value: "xinference", group: "local" },
  { name: "llamacpp", value: "llamacpp", group: "local" },
  { name: "vllm", value: "vllm", group: "local" },
  { name: "MindIE", value: "MindIE", group: "local" },
];

export const bishengModelProvider: ModelProviderEntry = {
  name: "bishengRT",
  value: "bisheng_rt",
  group: "local",
};

const OPENAI_COMPATIBLE_SEARCH_WORDS = [
  "custom",
  "compatible",
  "one api",
  "oneapi",
  "gateway",
  "proxy",
];

/** Label match, plus synonyms that should still find the OpenAI-compatible type. */
export function matchesProviderSearch(
  keyword: string,
  option: { value: string | number; label: string },
  localizedWords: string,
): boolean {
  const word = keyword.trim().toLowerCase();
  if (option.label.toLowerCase().includes(word)) return true;
  if (option.value !== "openai_compatible") return false;
  return [...OPENAI_COMPATIBLE_SEARCH_WORDS, ...localizedWords.split(",")].some(
    (item) => item.trim().toLowerCase().includes(word),
  );
}

export function providerSelectOptions(
  providers: ModelProviderEntry[],
  groupLabel: (group: NonNullable<ModelProviderEntry["group"]>) => string,
) {
  return providers
    .filter((model) => model.value)
    .map((model) => ({
      value: model.value,
      label: model.name,
      group: model.group ? groupLabel(model.group) : undefined,
    }));
}
