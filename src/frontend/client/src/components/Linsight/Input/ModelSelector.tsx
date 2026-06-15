/**
 * F035 Track H: model selector on the right side of the task-mode input.
 * Options come from the daily-chat model list (bsConfig.models — same source
 * as the daily input's selector); the default selection is the admin-marked
 * Linsight default model (`linsight_default_model_id` from /api/v1/llm/workbench),
 * falling back to the first option when absent. The picked id is sent as the
 * `model` field of the task submission.
 */
import { useQuery } from '@tanstack/react-query';
import { useEffect, useMemo } from 'react';
import { getLinsightModelConfig } from '~/api/linsight';
import { Select, SelectContent, SelectItem, SelectTrigger } from '~/components/ui/Select';
import { useGetBsConfig } from '~/hooks/queries/data-provider';

interface ModelSelectorProps {
    value: string;
    disabled?: boolean;
    onChange: (modelId: string) => void;
}

export function ModelSelector({ value, disabled = false, onChange }: ModelSelectorProps) {
    const { data: bsConfig } = useGetBsConfig();
    const { data: linsightModelCfg } = useQuery({
        queryKey: ['linsightModelConfig'],
        queryFn: getLinsightModelConfig,
        refetchOnWindowFocus: false,
        refetchOnReconnect: false,
        refetchOnMount: false,
    });

    // Dedup by model id — multiple LLM servers can expose the same model.
    const options = useMemo(() => {
        const models = (bsConfig as any)?.models || [];
        const seen = new Set<string>();
        return models.filter((opt: any) => {
            const id = String(opt.id);
            if (seen.has(id)) return false;
            seen.add(id);
            return true;
        });
    }, [bsConfig]);

    const defaultId = useMemo(() => {
        if (options.length === 0) return '';
        const adminDefault = linsightModelCfg?.linsight_default_model_id;
        if (adminDefault != null && options.some((opt: any) => String(opt.id) === String(adminDefault))) {
            return String(adminDefault);
        }
        return String(options[0].id);
    }, [options, linsightModelCfg]);

    // Apply the default when nothing is selected yet, or repair an invalid value.
    useEffect(() => {
        if (!defaultId) return;
        const valid = value && options.some((opt: any) => String(opt.id) === String(value));
        if (!valid) onChange(defaultId);
    }, [defaultId, value, options, onChange]);

    const label = useMemo(() => {
        const current = options.find((opt: any) => String(opt.id) === String(value));
        return current?.displayName ?? current?.name ?? '';
    }, [options, value]);

    if (options.length === 0) return null;

    return (
        <Select value={String(value)} disabled={disabled} onValueChange={onChange}>
            <SelectTrigger className="h-8 w-auto min-w-0 max-w-[min(40vw,220px)] touch-mobile:max-w-[min(40vw,140px)] gap-1 overflow-hidden border-none bg-transparent px-2 text-[#4E5969] shadow-none outline-none hover:bg-black/5 focus:ring-0">
                <span className="block min-w-0 overflow-hidden text-ellipsis whitespace-nowrap text-[13px] font-normal">
                    {label}
                </span>
            </SelectTrigger>
            <SelectContent className="bg-white">
                {options.map((opt: any) => (
                    <SelectItem key={String(opt.id)} value={String(opt.id)}>
                        {opt.displayName ?? opt.name}
                    </SelectItem>
                ))}
            </SelectContent>
        </Select>
    );
}
