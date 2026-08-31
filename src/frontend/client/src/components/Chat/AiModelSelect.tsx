// @ts-strict-ignore
import { memo, useEffect, useMemo } from "react";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
} from "~/components/ui/Select";
import type { BsConfig } from "~/types/chat";
import { ModelAvailabilityOption } from "./ModelAvailabilityOption";

interface AiModelSelectProps {
    options?: BsConfig["models"];
    value: number;
    disabled: boolean;
    /** User-initiated selection (Select onValueChange). */
    onChange: (value: string) => void;
    /**
     * Programmatic value repairs from the effect below (invalid/ mismatched
     * current value). Falls back to onChange when not provided. Parents that
     * track "manual vs default" selections should pass this so auto-repairs
     * are not mistaken for a user pick.
     */
    onAutoChange?: (value: string) => void;
}

export const AiModelSelect = memo(
    ({ options, value, disabled, onChange, onAutoChange }: AiModelSelectProps) => {
        // Dedup by model id — multiple LLM servers can expose the same model,
        // which otherwise produces duplicate entries in the dropdown.
        const uniqueOptions = useMemo(() => {
            if (!options) return [];
            const seen = new Set<string>();
            return options.filter((opt) => {
                // Radix <SelectItem> throws when its value is an empty string.
                // A stale / mis-configured workbench model can carry a blank id
                // (older backends don't sanitize it out), so drop those here —
                // never render <SelectItem value="">, which crashes the page.
                if (opt?.id == null || String(opt.id) === "") return false;
                const id = String(opt.id);
                if (seen.has(id)) return false;
                seen.add(id);
                return true;
            });
        }, [options]);

        const currentOption = useMemo(() => {
            if (uniqueOptions.length === 0 || value == null) return undefined;
            return uniqueOptions.find(
                (opt) => String(opt.id) === String(value)
            );
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
        }, [uniqueOptions, value]);

        return (
            <Select
                value={useMemo(() => value + "", [value])}
                disabled={disabled}
                onValueChange={onChange}
            >
                <SelectTrigger className="h-8 w-auto min-w-0 max-w-[min(50vw,288px)] touch-mobile:max-w-[min(60vw,200px)] touch-mobile:px-1.5 gap-1 overflow-hidden rounded-lg border-none bg-transparent px-2 text-text-2 shadow-none outline-none hover:bg-fill-1 focus:ring-0">
                    <div className="min-w-0 flex-1 overflow-hidden">
                        {currentOption ? <ModelAvailabilityOption model={currentOption} showDescription={false} /> : null}
                    </div>
                </SelectTrigger>
                {/* Width auto-fits the longest model displayName, bounded so it
                    doesn't shrink absurdly narrow on 2-char names or balloon on
                    very long ones. `auto` (see SelectContent) keeps the popup
                    from being forced to the trigger's width. No flash on open:
                    the model list is already in memory via `options`. */}
                <SelectContent
                    auto
                    className="bg-white w-auto min-w-[100px] max-w-[240px] rounded-2xl"
                    viewportClassName="flex flex-col gap-1 p-3"
                >
                    {uniqueOptions.map((opt) => (
                        <SelectItem key={opt.id + ""} value={opt.id + ""} textValue={opt.displayName} className="h-8 rounded-lg">
                            <ModelAvailabilityOption model={opt} />
                        </SelectItem>
                    ))}
                </SelectContent>
            </Select>
        );
    }
);

AiModelSelect.displayName = "AiModelSelect";

export default AiModelSelect;
