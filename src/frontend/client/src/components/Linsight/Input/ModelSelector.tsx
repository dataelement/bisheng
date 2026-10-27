/**
 * F035 Track H: model selector on the right side of the task-mode input.
 * Options come from the daily-chat model list (bsConfig.models — same source
 * as the daily input's selector); the default selection is the admin-marked
 * Linsight default model (`linsight_default_model_id` from /api/v1/llm/workbench),
 * falling back to the first option when absent. The picked id is sent as the
 * `model` field of the task submission.
 */
import { Select } from '@bisheng/ui';
import { useQuery } from '@tanstack/react-query';
import { useEffect, useMemo } from 'react';
import { getLinsightModelConfig } from '~/api/linsight';
import { useLocalize } from '~/hooks';
import { useGetBsConfig } from '~/hooks/queries/data-provider';
import useSelectCopy from '~/hooks/useSelectCopy';

interface ModelSelectorProps {
    value: string;
    disabled?: boolean;
    onChange: (modelId: string) => void;
}

export function ModelSelector({ value, disabled = false, onChange }: ModelSelectorProps) {
    const localize = useLocalize();
    const selectCopy = useSelectCopy();
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
            // A stale / mis-configured workbench model can carry a blank id
            // (older backends don't sanitize it out); an option without a
            // usable value can never be picked, so drop those here.
            if (opt?.id == null || String(opt.id) === "") return false;
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

    const selectOptions = useMemo(
        () =>
            options.map((opt) => ({
                value: String(opt.id),
                label: opt.displayName ?? opt.name,
                description: opt.description || undefined,
            })),
        [options],
    );

    if (options.length === 0) return null;

    return (
        <Select
            {...selectCopy}
            variant="ghost"
            options={selectOptions}
            value={value ? String(value) : null}
            disabled={disabled}
            onChange={(next) => next != null && onChange(String(next))}
            aria-label={localize('com_ui_select_model')}
            className="min-w-0 max-w-[min(40vw,220px)] max-md:max-w-[min(40vw,140px)]"
            panelClassName="max-w-[240px]"
        />
    );
}
