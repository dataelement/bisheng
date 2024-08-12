import { Button } from "@/components/bs-ui/button";
import { Label } from "@/components/bs-ui/label";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";
import Cascader from "@/components/bs-ui/select/cascader";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import { getKnowledgeModelConfig, updateKnowledgeModelConfig } from "@/controllers/API/finetune";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";


const ModelSelect = ({ required = false, label, tooltipText, value, options, onChange }) => {
    return (
        <div>
            <Label className="bisheng-label">
                <span>{label}</span>
                {required && <span className="text-red-500 text-xs">*</span>}
                {tooltipText && <QuestionTooltip className="relative top-0.5 ml-1" content={tooltipText} />}
            </Label>
            <Select value={value} onValueChange={onChange}>
                <SelectTrigger>
                    <SelectValue placeholder="" />
                </SelectTrigger>
                <SelectContent>
                    <SelectGroup>
                        {options.map((item) => (
                            <SelectItem key={item.id} value={item.id}>{item.model_name}</SelectItem>
                        ))}
                    </SelectGroup>
                </SelectContent>
            </Select>
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
    const [loading, setLoading] = useState(false);

    useEffect(() => {
        setLoading(true)
        getKnowledgeModelConfig().then(config => {
            const { embedding_model_id, extract_title_model_id, qa_similar_model_id, source_model_id } = config
            setForm({
                embeddingModelId: embedding_model_id,
                sourceModelId: extract_title_model_id,
                extractModelId: qa_similar_model_id,
                qaSimilarModelId: source_model_id
            })
            setLoading(false)
        });
    }, []);

    const embeddingValue = useMemo(() => {
        let value = []
        if (!form.embeddingModelId) return value
        embeddings.some(embedding => {
            const model = embedding.children.find(el => el.value === form.embeddingModelId)
            if (model) {
                value = [{ value: embedding.value, label: embedding.label }, { value: model.value, label: model.label }]
                return true
            }
        })
        return value
    }, [form.embeddingModelId])
    console.log('em :>> ', embeddingValue);

    const { message } = useToast()
    const handleSave = () => {
        const { embeddingModelId, extractModelId, qaSimilarModelId, sourceModelId } = form
        const errors = []
        if (!embeddingModelId) {
            errors.push(t('model.defaultEmbeddingModel') + t('bs:required'))
        }
        if (!sourceModelId) {
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

    return (
        <div className="max-w-[520px] mx-auto gap-y-4 flex flex-col mt-16">
            <div>
                <Label className="bisheng-label">{t('model.defaultEmbeddingModel')}<span className="text-red-500 text-xs">*</span></Label>
                {
                    !loading && <Cascader
                        defaultValue={embeddingValue}
                        options={embeddings}
                        onChange={(val) => setForm({ ...form, embeddingModelId: val[1] })}
                    />
                }
            </div>
            <ModelSelect
                label={t('model.sourceTracingModel')}
                tooltipText={t('model.sourceTracingModelTooltip')}
                value={form.sourceModelId}
                options={llmOptions}
                onChange={(val) => setForm({ ...form, sourceModelId: val })}
            />
            <ModelSelect
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