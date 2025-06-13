import { Button } from "@/components/bs-ui/button";
import { Label } from "@/components/bs-ui/label";
import { useToast } from "@/components/bs-ui/toast/use-toast";
// import { getAuditModelConfig, updateAuditModelConfig } from "@/controllers/API/finetune";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ModelSelect } from "./KnowledgeModel";
import { LoadingIcon } from "@/components/bs-icons/loading";
import { setAuditDefaultModel, updateAuditDefaultModel } from "@/controllers/API/finetune";

export default function AuditModelConfig({ llmOptions, onBack }) {
    const { t } = useTranslation('model')
    const [selectedModel, setSelectedModel] = useState(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        setLoading(true);
        setAuditDefaultModel().then(res => {
            setSelectedModel(res.model_id);
            setLoading(false);
        });
    }, []);

    const { message } = useToast();

    const handleSave = () => {
        if (!selectedModel) {
            return message({ variant: 'error', description: t('model.auditModel') + t('bs:required') });
        }
        const data = {
            model_id: selectedModel
        };
        captureAndAlertRequestErrorHoc(updateAuditDefaultModel(data).then(res => {
            message({ variant: 'success', description: t('model.saveSuccess') });
        }));
    };

    if (loading) return (
        <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
            <LoadingIcon />
        </div>
    );

    return (
        <div className="max-w-[520px] mx-auto">
            <div className="mt-10">
                {/* <Label className="bisheng-label">{t('model.auditModel')}<span className="text-red-500 text-xs">*</span></Label> */}
                <Label className="bisheng-label">违规审查模型<span className="text-red-500 text-xs">*</span></Label>
                <ModelSelect
                    label={''}
                    value={selectedModel}
                    options={llmOptions}
                    onChange={(val) => setSelectedModel(val)}
                />
            </div>
            <div className="mt-10 text-center space-x-6">
                <Button className="px-6" variant="outline" onClick={onBack}>{t('model.cancel')}</Button>
                <Button className="px-10" onClick={handleSave}>{t('model.save')}</Button>
            </div>
        </div>
    );
}
