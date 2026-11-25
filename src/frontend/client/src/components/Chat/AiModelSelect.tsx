import { Cascader, Tooltip, type CascaderOption, type CascaderPath } from "@bisheng/ui";
import { memo, useEffect, useMemo } from "react";
import { useLocalize } from "~/hooks";
import useSelectCopy from "~/hooks/useSelectCopy";
import type { BsConfig, ModelPricingHint } from "~/types/chat";

/**
 * Credit ratio after the model name: "3.00x" or "Free"; nothing when the server sent none.
 * The base model reads "1.00x" without a word: picker cells are narrow and truncate long labels.
 */
function modelRatioText(hint: ModelPricingHint | null | undefined, free: string): string {
  if (!hint) return "";
  if (hint.free) return free;
  return hint.ratio ? `${hint.ratio}x` : "";
}

interface AiModelSelectProps {
  options?: BsConfig["models"];
  value: number;
  disabled: boolean;
  /** Shown as a tooltip while the selector is disabled, to say when it comes back. */
  disabledReason?: string;
  /** User-initiated model selection. */
  onChange: (value: string) => void;
  /**
   * Programmatic value repairs from the effect below (invalid/ mismatched
   * current value). Falls back to onChange when not provided. Parents that
   * track "manual vs default" selections should pass this so auto-repairs
   * are not mistaken for a user pick.
   */
  onAutoChange?: (value: string) => void;
}

const AiModelSelect = memo(({ options, value, disabled, disabledReason, onChange, onAutoChange }: AiModelSelectProps) => {
  const localize = useLocalize();
  const selectCopy = useSelectCopy();
  // Dedup by model id — multiple LLM servers can expose the same model,
  // which otherwise produces duplicate entries in the dropdown.
  const uniqueOptions = useMemo(() => {
    if (!options) return [];
    const seen = new Set<string>();
    return options.filter((opt) => {
      // A stale / mis-configured workbench model can carry a blank id
      // (older backends don't sanitize it out); an option without a
      // usable value can never be picked, so drop those here.
      if (opt?.id == null || String(opt.id) === "") return false;
      const id = String(opt.id);
      if (seen.has(id)) return false;
      seen.add(id);
      return true;
    });
  }, [options]);

  const unknownProvider = localize("modelPicker.unknownProvider");
  const ratioFree = localize("modelPicker.ratioFree");
  const { cascaderOptions, modelPaths } = useMemo(() => {
    const groups = new Map<string, CascaderOption>();
    const paths = new Map<string, CascaderPath>();
    for (const model of uniqueOptions) {
      const providerName = model.provider_name?.trim() || unknownProvider;
      const providerKey = `provider:${model.provider_id ?? model.provider_name?.trim() ?? "unknown"}`;
      if (!groups.has(providerKey)) {
        groups.set(providerKey, { value: providerKey, label: providerName, children: [] });
      }
      const id = String(model.id);
      const name = model.displayName?.trim() || model.name;
      // The shared Cascader takes plain-text labels, so the ratio rides in the label text.
      const ratio = modelRatioText(model.pricing_hint, ratioFree);
      groups.get(providerKey)!.children!.push({ value: id, label: ratio ? `${name} · ${ratio}` : name });
      paths.set(id, [providerKey, id]);
    }
    return { cascaderOptions: [...groups.values()], modelPaths: paths };
  }, [uniqueOptions, unknownProvider, ratioFree]);

  // Auto-select first option when current value is invalid
  useEffect(() => {
    if (uniqueOptions.length === 0) return;
    const repair = onAutoChange ?? onChange;
    const hasCurrent = uniqueOptions.find((opt) => String(opt.id) === String(value));
    if (!hasCurrent) {
      // Spec: default falls back to the "latest" configured model,
      // which is the last entry in the admin-ordered list.
      repair(String(uniqueOptions[uniqueOptions.length - 1].id));
    } else if (String(hasCurrent.id) !== String(value)) {
      // Type/normalization fix only — never fire for an exact match,
      // otherwise a mere mount would look like a user selection.
      repair(String(hasCurrent.id));
    }
  }, [uniqueOptions, value, onAutoChange, onChange]);

  const cascader = (
    <Cascader
      {...selectCopy}
      variant="ghost"
      options={cascaderOptions}
      value={modelPaths.get(String(value)) ?? null}
      disabled={disabled}
      showSearch
      autoWidth
      filterOption={(keyword, path) => {
        const query = keyword.toLowerCase();
        const modelId = path[path.length - 1]?.value;
        const model = uniqueOptions.find(option => String(option.id) === String(modelId));
        return [...path.map(option => option.label), model?.description ?? ""]
          .some(label => label.toLowerCase().includes(query));
      }}
      onChange={(path) => { if (path?.length === 2) onChange(String(path[1])); }}
      backLabel={localize("modelPicker.back")}
      searchPlaceholder={localize("com_ui_select_search_model")}
      aria-label={localize("com_ui_select_model")}
      className="min-w-0 max-w-[min(50vw,288px)] touch-mobile:max-w-[min(60vw,200px)]"
    />
  );
  // The tooltip adds a hover zone around a disabled trigger, so it is mounted
  // only while there is a reason to show.
  return disabled && disabledReason ? <Tooltip content={disabledReason}>{cascader}</Tooltip> : cascader;
});

AiModelSelect.displayName = "AiModelSelect";

export default AiModelSelect;
