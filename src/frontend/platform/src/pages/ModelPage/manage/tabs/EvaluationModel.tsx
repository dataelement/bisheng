import { Button } from "@/components/bs-ui/button";
import { Label } from "@/components/bs-ui/label";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { getEvaluationModelEnvelope, updateEvaluationModelConfig } from "@/controllers/API/finetune";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ModelSelect } from "./KnowledgeModel";
import { LoadingIcon } from "@/components/bs-icons/loading";
import { FallbackBlockedBanner, InheritedBadge } from "../SystemConfigBanners";
import { useSystemConfigEnvelope } from "../useSystemConfigEnvelope";

export default function EvaluationModel({ llmOptions, onBack }) {
    const { t } = useTranslation('model')
    const [selectedModel, setSelectedModel] = useState(null);
    const { config, loading, inheritedFromRoot, fallbackBlocked, clearInherited } =
        useSystemConfigEnvelope<any>(getEvaluationModelEnvelope)

    useEffect(() => {
        if (config) setSelectedModel(config.model_id)
    }, [config]);

    const handleModelChange = (val: any) => {
        clearInherited()
        setSelectedModel(val)
    }

    const { message } = useToast()
    const handleSave = () => {
        if (!selectedModel) {
            return message({ variant: 'error', description: t('model.defaultEvaluationFeature') + t('bs:required') })
        }
        const data = {
            model_id: selectedModel
        };
        captureAndAlertRequestErrorHoc(updateEvaluationModelConfig(data).then(res => {
            message({ variant: 'success', description: t('model.saveSuccess') })
        }));
    };

    if (loading) return <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
        <LoadingIcon />
    </div>

    return (
        <div className="max-w-[520px] mx-auto">
            <FallbackBlockedBanner visible={fallbackBlocked} />
            <div className="mt-10">
                <Label className="bisheng-label">
                    {t('model.defaultEvaluationFeature')}<span className="text-red-500 text-xs">*</span>
                    <InheritedBadge visible={inheritedFromRoot} />
                </Label>
                <ModelSelect
                    label={''}
                    value={selectedModel}
                    options={llmOptions}
                    onChange={handleModelChange}
                />
            </div>
            <div className="mt-10 text-center space-x-6">
                <Button className="px-6" variant="outline" onClick={onBack}>{t('model.cancel')}</Button>
                <Button className="px-10" onClick={handleSave}>{t('model.save')}</Button>
            </div>
        </div>
    );
}
