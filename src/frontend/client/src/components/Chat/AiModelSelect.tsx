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
        const label = useMemo(() => {
            if (!options || options.length === 0 || value == null) return "";
            const currentOpt = options.find(
                (opt) => String(opt.id) === String(value)
            );
            return currentOpt?.displayName ?? "";
        }, [options, value]);

        // Auto-select first option when current value is invalid
        useEffect(() => {
            if (!options || options.length === 0) return;
            const hasCurrent = options.find(
                (opt) => String(opt.id) === String(value)
            );
            if (!hasCurrent) {
                // Spec: default falls back to the "latest" configured model,
                // which is the last entry in the admin-ordered list.
                onChange(String(options[options.length - 1].id));
            } else {
                onChange(hasCurrent.id);
            }
        }, [options, value]);

        return (
            <Select
                value={useMemo(() => value + "", [value])}
                disabled={disabled}
                onValueChange={onChange}
            >
                <SelectTrigger className="h-8 w-auto min-w-0 max-w-[min(30vw,120px)] gap-1 overflow-hidden border-none bg-transparent px-2 text-[#4E5969] shadow-none outline-none hover:bg-black/5 focus:ring-0">
                    <div className="min-w-0 flex-1 overflow-hidden">
                        <span className="block min-w-0 overflow-hidden text-ellipsis whitespace-nowrap text-[14px] font-normal">
                            {label}
                        </span>
                    </div>
                </SelectTrigger>
                <SelectContent className="bg-white">
                    {options?.map((opt) => (
                        <SelectItem key={opt.key} value={opt.id + ""}>
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
