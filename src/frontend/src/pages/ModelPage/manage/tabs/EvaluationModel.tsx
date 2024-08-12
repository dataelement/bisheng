import { Button } from "@/components/bs-ui/button";
import { Label } from "@/components/bs-ui/label";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { getEvaluationModelConfig, updateEvaluationModelConfig } from "@/controllers/API/finetune";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

export default function EvaluationModel({ llmOptions, onBack }) {
    const { t } = useTranslation('model')
    const [selectedModel, setSelectedModel] = useState(null);
    useEffect(() => {
        getEvaluationModelConfig().then(res => setSelectedModel(res.model_id))
    }, []);

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

    return (
        <div className="max-w-[520px] mx-auto">
            <div className="mt-10">
                <Label className="bisheng-label">{t('model.defaultEvaluationFeature')}<span className="text-red-500 text-xs">*</span></Label>
                <Select value={selectedModel} onValueChange={(val) => setSelectedModel(val)}>
                    <SelectTrigger className="mt-2">
                        <SelectValue placeholder={t('model.selectModel')} />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectGroup>
                            {llmOptions.map((option) => (
                                <SelectItem key={option.id} value={option.id}>{option.model_name}</SelectItem>
                            ))}
                        </SelectGroup>
                    </SelectContent>
                </Select>
            </div>
            <div className="mt-10 text-center space-x-6">
                <Button className="px-6" variant="outline" onClick={onBack}>{t('model.cancel')}</Button>
                <Button className="px-10" onClick={handleSave}>{t('model.save')}</Button>
            </div>
        </div>
    );
}
