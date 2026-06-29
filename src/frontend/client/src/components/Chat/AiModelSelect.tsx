import { Rotate3DIcon } from "lucide-react";
import { memo, useEffect, useMemo } from "react";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
} from "~/components/ui/Select";
import type { BsConfig } from "~/types/chat";

interface AiModelSelectProps {
    options?: BsConfig["models"];
    value: number;
    disabled: boolean;
    onChange: (value: string) => void;
}

const AiModelSelect = memo(
    ({ options, value, disabled, onChange }: AiModelSelectProps) => {
        // Dedup by model id — multiple LLM servers can expose the same model,
        // which otherwise produces duplicate entries in the dropdown.
        const uniqueOptions = useMemo(() => {
            if (!options) return [];
            const seen = new Set<string>();
            return options.filter((opt) => {
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
            const hasCurrent = uniqueOptions.find(
                (opt) => String(opt.id) === String(value)
            );
            if (!hasCurrent) {
                // Spec: default falls back to the "latest" configured model,
                // which is the last entry in the admin-ordered list.
                onChange(String(uniqueOptions[uniqueOptions.length - 1].id));
            } else {
                onChange(hasCurrent.id);
            }
        }, [uniqueOptions, value]);

        return (
            <Select
                value={useMemo(() => value + "", [value])}
                disabled={disabled}
                onValueChange={onChange}
            >
                <SelectTrigger className="h-8 w-auto min-w-0 max-w-[min(50vw,288px)] touch-mobile:max-w-[min(60vw,200px)] touch-mobile:px-1.5 gap-1 overflow-hidden rounded-lg border-none bg-transparent px-2 text-[#4E5969] shadow-none outline-none hover:bg-[#f8f8f8] focus:ring-0">
                    <div className="min-w-0 flex-1 overflow-hidden">
                        <span className="block min-w-0 overflow-hidden text-ellipsis whitespace-nowrap text-[14px] font-normal">
                            {label}
                        </span>
                    </div>
                </SelectTrigger>
                {/* Width auto-fits the longest model displayName, bounded so it
                    doesn't shrink absurdly narrow on 2-char names or balloon on
                    very long ones. `auto` (see SelectContent) keeps the popup
                    from being forced to the trigger's width. No flash on open:
                    the model list is already in memory via `options`. */}
                <SelectContent auto className="bg-white w-auto min-w-[140px] max-w-[280px]">
                    {uniqueOptions.map((opt) => (
                        <SelectItem key={opt.id + ""} value={opt.id + ""}>
                            {opt.displayName}
                        </SelectItem>
                    ))}
                </SelectContent>
            </Select>
        );
    }
);

AiModelSelect.displayName = "AiModelSelect";

export default AiModelSelect;
