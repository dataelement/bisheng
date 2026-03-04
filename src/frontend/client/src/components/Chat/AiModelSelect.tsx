import { Rotate3DIcon } from "lucide-react";
import { memo, useEffect, useMemo } from "react";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
} from "~/components/ui/Select";
import type { BsConfig } from "~/data-provider/data-provider/src";

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
                onChange(String(options[0].id));
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
                <SelectTrigger className="h-7 rounded-full px-2 text-gray-500 bg-white dark:bg-transparent">
                    <div className="flex gap-2">
                        <Rotate3DIcon size="16" />
                        <span className="text-xs font-normal">{label}</span>
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
