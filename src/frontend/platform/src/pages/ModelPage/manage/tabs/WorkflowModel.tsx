import { LoadingState } from "@/components/bs-icons/loading/LoadingState";
import { Button, toast } from '@bisheng/ui';


import { Label } from "@/components/bs-ui/label";

import { getLlmDefaultModelEnvelope, setLlmDefaultModel } from "@/controllers/API/finetune";
import { showApiError } from "@/controllers/request";
import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { ModelSelect } from "./KnowledgeModel";
import { FallbackBlockedBanner, InheritedBadge } from "../SystemConfigBanners";
import { useSystemConfigEnvelope } from "../useSystemConfigEnvelope";

export default function WorkflowModel({ llmOptions, onBack }) {
    const { t } = useTranslation('model')
    const [selectedModel, setSelectedModel] = useState(null);
    const [saving, setSaving] = useState(false);
    const queryClient = useQueryClient();
    const { config, loading, inheritedFromRoot, fallbackBlocked, reload } =
        useSystemConfigEnvelope<any>(getLlmDefaultModelEnvelope)

    useEffect(() => {
        if (config) setSelectedModel(config.model_id)
    }, [config]);

    const handleModelChange = (val: any) => {
        setSelectedModel(val)
    }


    const handleSave = async () => {
        if (saving) return;
        if (!selectedModel) {
            return toast.show({ type: 'error', message: String(t('model.defaultEvaluationFeature') + t('bs:required')) })
        }
        const data = {
            model_id: selectedModel
        };

        setSaving(true);
        try {
            await setLlmDefaultModel(data);
            toast.show({ type: 'success', message: String(t('model.saveSuccess') ?? '') });
            await queryClient.invalidateQueries({ queryKey: ['system-model-settings'] });
            await queryClient.invalidateQueries({ queryKey: ['system-model-settings-impact'] });
            await reload();
        } catch (error) {
            showApiError(error);
        } finally {
            setSaving(false);
        }
    };

    if (loading) return <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
        <LoadingState size="page" />
    </div>

    return (
        <div className="max-w-[520px] mx-auto">
            <FallbackBlockedBanner visible={fallbackBlocked} />
            <div className="mt-10">
                <Label className="bisheng-label">
                    {t('model.modelsAndRAGNodes')}<span className="text-red-500 text-xs">*</span>
                    <InheritedBadge visible={inheritedFromRoot} />
                </Label>
                <ModelSelect
                    close
                    label={''}
                    value={selectedModel}
                    options={llmOptions}
                    onChange={handleModelChange}
                />
            </div>
            {inheritedFromRoot && <p className="mt-4 text-xs text-muted-foreground">{t('model.draftSourceHelp')}</p>}
            <div className="mt-10 text-center space-x-6">
                <Button variant="outlined" onClick={onBack} color="default">{t('model.cancel')}</Button>
                <Button disabled={saving || !config} onClick={handleSave}>{t(inheritedFromRoot ? 'model.saveLocalConfiguration' : 'model.save')}</Button>
            </div>
        </div>
    );
}
