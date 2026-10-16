// @ts-strict-ignore
import { Check, ChevronDown } from "lucide-react";
import { Combobox, ComboboxItem, ComboboxList, ComboboxProvider } from "@ariakit/react";
import { Popover, PopoverContent, PopoverTrigger } from "~/components/ui/Popover";
import { useLocalize } from "~/hooks";
import "./AiModelSelect.css";
import { memo, useEffect, useMemo, useState } from "react";
import type { BsConfig } from "~/types/chat";

interface AiModelSelectProps {
    options?: BsConfig["models"];
    value: number;
    disabled: boolean;
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

const AiModelSelect = memo(
    ({ options, value, disabled, onChange, onAutoChange }: AiModelSelectProps) => {
        const localize = useLocalize();
        const [open, setOpen] = useState(false);
        const [query, setQuery] = useState("");
        // Dedup by model id — multiple LLM servers can expose the same model,
        // which otherwise produces duplicate entries in the dropdown.
        const uniqueOptions = useMemo(() => {
            if (!options) return [];
            const seen = new Set<string>();
            return options.filter((opt) => {
                // Only models with a stable id can be selected and persisted.
                if (opt?.id == null || String(opt.id) === "") return false;
                const id = String(opt.id);
                if (seen.has(id)) return false;
                seen.add(id);
                return true;
            });
        }, [options]);

        const label = useMemo(() => {
            if (uniqueOptions.length === 0 || value == null) return "";
            const currentOpt = uniqueOptions.find(
                (opt) => String(opt.id) === String(value)
            );
            return currentOpt?.displayName ?? "";
        }, [uniqueOptions, value]);

        // Auto-select first option when current value is invalid
        useEffect(() => {
            if (uniqueOptions.length === 0) return;
            const repair = onAutoChange ?? onChange;
            const hasCurrent = uniqueOptions.find(
                (opt) => String(opt.id) === String(value)
            );
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

        const matches = uniqueOptions.filter((option) =>
            `${option.displayName} ${option.name} ${option.description ?? ""}`
                .toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())
        );

        return (
            <Popover open={open && !disabled} onOpenChange={(next) => { setOpen(next); setQuery(""); }}>
                <PopoverTrigger asChild>
                    <button type="button" disabled={disabled} className="dsh-composer-control dsh-model-trigger">
                        <span>{label || localize("com_ui_select_model")}</span>
                        <ChevronDown size={12} aria-hidden className={open ? "rotate-180" : ""} />
                    </button>
                </PopoverTrigger>
                <PopoverContent side="top" align="end" sideOffset={8} collisionPadding={16}
                    className="dsh-chat-menu dsh-model-menu" aria-label={localize("com_ui_select_model")}>
                    <ComboboxProvider open includesBaseElement={false} value={query} setValue={setQuery} resetValueOnHide>
                        <Combobox autoFocus autoSelect className="dsh-model-search"
                            aria-label={localize("com_ui_select_search_model")}
                            placeholder={localize("com_ui_select_search_model")} />
                        <ComboboxList className="dsh-model-options" aria-label={localize("com_ui_select_model")}>
                            {matches.map((option) => (
                                <ComboboxItem key={option.id} value={option.displayName}
                                    className="dsh-model-option" aria-selected={String(option.id) === String(value)}
                                    title={option.description || option.displayName}
                                    onClick={() => { onChange(String(option.id)); setOpen(false); setQuery(""); }}>
                                    <span className="dsh-model-copy">
                                        <span className="dsh-model-name">{option.displayName}</span>
                                        {option.description && <span className="dsh-model-description">{option.description}</span>}
                                    </span>
                                    {String(option.id) === String(value) && <Check size={14} aria-hidden />}
                                </ComboboxItem>
                            ))}
                            {matches.length === 0 && <div className="dsh-model-empty" role="status">
                                {localize("com_list_no_results")}
                            </div>}
                        </ComboboxList>
                    </ComboboxProvider>
                </PopoverContent>
            </Popover>
        );
    }
);

AiModelSelect.displayName = "AiModelSelect";

export default AiModelSelect;
