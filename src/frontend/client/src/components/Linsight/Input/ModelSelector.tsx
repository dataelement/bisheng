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
import { ModelAvailabilityOption, WorkbenchModelOption } from '~/components/Chat/ModelAvailabilityOption';
import { getTaskDefaultModelId, getUniqueWorkbenchModels } from './modelSelectorHelpers';

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
        const models: WorkbenchModelOption[] = bsConfig?.models || [];
        return getUniqueWorkbenchModels(models);
    }, [bsConfig]);

    const defaultId = useMemo(() => {
        return getTaskDefaultModelId(options, linsightModelCfg?.linsight_default_model_id);
    }, [options, linsightModelCfg]);

    // Apply the default when nothing is selected yet, or repair an invalid value.
    useEffect(() => {
        if (!defaultId) return;
        const valid = value && options.some((opt) => String(opt.id) === String(value));
        if (!valid) onChange(defaultId);
    }, [defaultId, value, options, onChange]);

    const label = useMemo(() => {
        return options.find((opt) => String(opt.id) === String(value));
    }, [options, value]);

    if (options.length === 0) return null;

    return (
        <Select value={String(value)} disabled={disabled} onValueChange={onChange}>
            <SelectTrigger className="h-8 w-auto min-w-0 max-w-[min(40vw,220px)] max-md:max-w-[min(40vw,140px)] gap-1 overflow-hidden border-none bg-transparent px-2 text-text-2 shadow-none outline-none hover:bg-fill-1 focus:ring-0">
                {label ? <ModelAvailabilityOption model={label} showDescription={false} /> : null}
            </SelectTrigger>
            {/* Mirrors AiModelSelect: `auto` skips the trigger-width floor so the
                popup fits the longest option between the clamps. */}
            <SelectContent auto className="bg-white w-auto min-w-[100px] max-w-[240px]">
                {options.map((opt) => (
                    <SelectItem key={String(opt.id)} value={String(opt.id)} textValue={opt.displayName ?? opt.name}>
                        <ModelAvailabilityOption model={opt} />
                    </SelectItem>
                ))}
            </SelectContent>
        </Select>
    );
}
