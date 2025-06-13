import { LoadingIcon } from "@/components/bs-icons/loading";
import { Button } from "@/components/bs-ui/button";
import { Label } from "@/components/bs-ui/label";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { getLlmDefaultModel, getVoiceDefaultModel, setLlmDefaultModel, setVoiceDefaultModel } from "@/controllers/API/finetune";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ModelSelect } from "./KnowledgeModel";

export default function SpeechModel({ llmOptions, onBack }) {
    const { t } = useTranslation('model')
    const [selectedTtsModel, setSelectedTtsModel] = useState(null);
    const [selectedSttModel, setSelectedSttModel] = useState(null);
    const [loading, setLoading] = useState(true)
    useEffect(() => {
        setLoading(true)
        getVoiceDefaultModel().then(res => {
            setSelectedTtsModel(res.tts_model_id)
            setSelectedSttModel(res.stt_model_id)
            setLoading(false)
        })
    }, []);

    const { message } = useToast()
    const handleSave = () => {
        if (!selectedTtsModel) {
            return message({ variant: 'error', description: t('model.ttsDefaultModal') + t('bs:required') })
        }
        if (!selectedSttModel) {
            return message({ variant: 'error', description: t('model.sttDefaultModal') + t('bs:required') })
        }
        const data = {
            tts_model_id: selectedTtsModel,
            stt_model_id: selectedSttModel,
        };

        captureAndAlertRequestErrorHoc(setVoiceDefaultModel(data).then(res => {
            message({ variant: 'success', description: t('model.saveSuccess') })
        }));
    };

    if (loading) return <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
        <LoadingIcon />
    </div>

    return (
        <div className="max-w-[520px] mx-auto">
            <div className="mt-10">
                <Label className="bisheng-label">{t('model.ttsDefaultModal')}<span className="text-red-500 text-xs">*</span></Label>
                <ModelSelect
                    label={''}
                    value={selectedTtsModel}
                    options={llmOptions}
                    onChange={(val) => setSelectedTtsModel(val)}
                />
            </div>
            <div className="mt-10">
                <Label className="bisheng-label">{t('model.sttDefaultModal')}<span className="text-red-500 text-xs">*</span></Label>
                <ModelSelect
                    label={''}
                    value={selectedSttModel}
                    options={llmOptions}
                    onChange={(val) => setSelectedSttModel(val)}
                />
            </div>
            <div className="mt-10 text-center space-x-6">
                <Button className="px-6" variant="outline" onClick={onBack}>{t('model.cancel')}</Button>
                <Button className="px-10" onClick={handleSave}>{t('model.save')}</Button>
            </div>
        </div>
    );
}
