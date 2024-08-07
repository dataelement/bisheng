import { Button } from "@/components/bs-ui/button";
import { Label } from "@/components/bs-ui/label";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";
import Cascader from "@/components/bs-ui/select/cascader";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import { getKnowledgeModelConfig, updateKnowledgeModelConfig } from "@/controllers/API/finetune";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { useEffect, useMemo, useState } from "react";


const ModelSelect = ({ label, tooltipText, value, options, onChange }) => {
    return (
        <div>
            <Label className="bisheng-label">
                <span>模型名称</span>
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
        captureAndAlertRequestErrorHoc(updateKnowledgeModelConfig({
            embedding_model_id: embeddingModelId,
            extract_title_model_id: extractModelId,
            qa_similar_model_id: qaSimilarModelId,
            source_model_id: sourceModelId
        }).then(res => {
            message({ variant: 'success', description: '保存成功' })
        }))
    };

    return (
        <div className="max-w-[520px] mx-auto gap-y-4 flex flex-col mt-16">
            <div>
                <Label className="bisheng-label">知识库默认embedding模型</Label>
                {
                    !loading && <Cascader
                        defaultValue={embeddingValue}
                        options={embeddings}
                        onChange={(val) => setForm({ ...form, embeddingModelId: val[1] })}
                    />
                }
            </div>
            <ModelSelect
                label="知识库溯源模型"
                tooltipText="用于知识库问答溯源，使用 LLM 自动从答案中提取关键词，来帮助用户快速定位到答案的可能来源段落，如果这里没有配置，则会使用 jieba 分词来输出答案中的关键词。"
                value={form.sourceModelId}
                options={llmOptions}
                onChange={(val) => setForm({ ...form, sourceModelId: val })}
            />
            <ModelSelect
                label="文档知识库总结模型"
                tooltipText="将文档内容总结为一个标题，然后将标题和chunk合并存储到向量库内, 不配置则不总结文档。"
                value={form.extractModelId}
                options={llmOptions}
                onChange={(val) => setForm({ ...form, extractModelId: val })}
            />
            <ModelSelect
                label="QA知识库相似问模型"
                tooltipText="用于生成 QA 知识库中的相似问题。"
                value={form.qaSimilarModelId}
                options={llmOptions}
                onChange={(val) => setForm({ ...form, qaSimilarModelId: val })}
            />
            <div className="mt-10 text-center space-x-6">
                <Button className="px-6" variant="outline" onClick={onBack}>取消</Button>
                <Button className="px-10" onClick={handleSave}>保存</Button>
            </div>
        </div>
    );
}