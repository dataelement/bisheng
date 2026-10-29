import { Select } from "@bisheng/ui";
import { memo, useEffect, useMemo } from "react";
import { useLocalize } from "~/hooks";
import useSelectCopy from "~/hooks/useSelectCopy";
import type { BsConfig } from "~/types/chat";

interface AiModelSelectProps {
  options?: BsConfig["models"];
  value: number;
  disabled: boolean;
  /** User-initiated selection (Select onChange). */
  onChange: (value: string) => void;
  /**
   * Programmatic value repairs from the effect below (invalid/ mismatched
   * current value). Falls back to onChange when not provided. Parents that
   * track "manual vs default" selections should pass this so auto-repairs
   * are not mistaken for a user pick.
   */
  onAutoChange?: (value: string) => void;
}

const AiModelSelect = memo(({ options, value, disabled, onChange, onAutoChange }: AiModelSelectProps) => {
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

  const selectOptions = useMemo(
    () =>
      uniqueOptions.map((opt) => ({
        value: String(opt.id),
        label: opt.displayName,
        description: opt.description || undefined,
      })),
    [uniqueOptions],
  );

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

  return (
    // Width bounds are layout only: the panel sizes to the longest
    // model name (narrow ghost trigger), and the model list is already
    // in memory via `options`, so there is no flash on open.
    <Select
      {...selectCopy}
      variant="ghost"
      options={selectOptions}
      value={value == null ? null : String(value)}
      disabled={disabled}
      onChange={(next) => next != null && onChange(String(next))}
      aria-label={localize("com_ui_select_model")}
      className="min-w-0 max-w-[min(50vw,288px)] touch-mobile:max-w-[min(60vw,200px)]"
      panelClassName="max-w-[240px]"
    />
  );
});

AiModelSelect.displayName = "AiModelSelect";

export default AiModelSelect;
