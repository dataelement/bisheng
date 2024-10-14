import { LoadingIcon } from "@/components/bs-icons/loading";
import { Button } from "@/components/bs-ui/button";
import { Label } from "@/components/bs-ui/label";
import Cascader from "@/components/bs-ui/select/cascader";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import { getKnowledgeModelConfig, updateKnowledgeModelConfig } from "@/controllers/API/finetune";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";


export const ModelSelect = ({ required = false, close = false, label, tooltipText = '', value, options, onChange }) => {

    const defaultValue = useMemo(() => {
        let _defaultValue = []
        if (!value) return _defaultValue
        options.some(option => {
            const model = option.children.find(el => el.value === value)
            if (model) {
                _defaultValue = [{ value: option.value, label: option.label }, { value: model.value, label: model.label }]
                return true
            }
        })
        // 无对应选项自动清空旧值
        if (_defaultValue.length === 0) onChange(null)
        return _defaultValue
    }, [value])

    return (
        <div>
            <Label className="bisheng-label">
                <span>{label}</span>
                {required && <span className="text-red-500 text-xs">*</span>}
                {tooltipText && <QuestionTooltip className="relative top-0.5 ml-1" content={tooltipText} />}
            </Label>
            <Cascader
                defaultValue={defaultValue}
                options={options}
                close={close}
                onChange={(val) => onChange(val[1])}
            />
        </div>
    );
};



export default function KnowledgeModel({ llmOptions, embeddings, onBack }) {
    const { t } = useTranslation('model')

    const [form, setForm] = useState({
        embeddingModelId: null,
        sourceModelId: null,
        extractModelId: null,
        qaSimilarModelId: null
    });

    const [loading, setLoading] = useState(true)
    useEffect(() => {
        setLoading(true)
        getKnowledgeModelConfig().then(config => {
            const { embedding_model_id, extract_title_model_id, qa_similar_model_id, source_model_id } = config
            setForm({
                embeddingModelId: embedding_model_id,
                sourceModelId: source_model_id,
                extractModelId: extract_title_model_id,
                qaSimilarModelId: qa_similar_model_id
            })
            setLoading(false)
        });
    }, []);

    const { message } = useToast()
    const handleSave = () => {
        const { embeddingModelId, extractModelId, qaSimilarModelId, sourceModelId } = form
        const errors = []
        if (!embeddingModelId) {
            errors.push(t('model.defaultEmbeddingModel') + t('bs:required'))
        }
        if (!qaSimilarModelId) {
            errors.push(t('model.qaSimilarModel') + t('bs:required'))
        }
        if (errors.length) return message({ variant: 'error', description: errors })

        captureAndAlertRequestErrorHoc(updateKnowledgeModelConfig({
            embedding_model_id: embeddingModelId,
            extract_title_model_id: extractModelId,
            qa_similar_model_id: qaSimilarModelId,
            source_model_id: sourceModelId
        }).then(res => {
            message({ variant: 'success', description: t('model.saveSuccess') })
        }))
    };

    if (loading) return <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
        <LoadingIcon />
    </div>

    return (
        <div className="max-w-[520px] mx-auto gap-y-4 flex flex-col mt-16">
            <ModelSelect
                required
                label={t('model.defaultEmbeddingModel')}
                value={form.embeddingModelId}
                options={embeddings}
                onChange={(val) => setForm({ ...form, embeddingModelId: val })}
            />
            <ModelSelect
                close
                label={t('model.sourceTracingModel')}
                tooltipText={t('model.sourceTracingModelTooltip')}
                value={form.sourceModelId}
                options={llmOptions}
                onChange={(val) => setForm({ ...form, sourceModelId: val })}
            />
            <ModelSelect
                close
                label={t('model.documentSummaryModel')}
                tooltipText={t('model.documentSummaryModelTooltip')}
                value={form.extractModelId}
                options={llmOptions}
                onChange={(val) => setForm({ ...form, extractModelId: val })}
            />
            <ModelSelect
                required
                label={t('model.qaSimilarModel')}
                tooltipText={t('model.qaSimilarModelTooltip')}
                value={form.qaSimilarModelId}
                options={llmOptions}
                onChange={(val) => setForm({ ...form, qaSimilarModelId: val })}
            />
            <div className="mt-10 text-center space-x-6">
                <Button className="px-6" variant="outline" onClick={onBack}>{t('model.cancel')}</Button>
                <Button className="px-10" onClick={handleSave}>{t('model.save')}</Button>
            </div>
        </div>
    );
}