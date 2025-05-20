import { LoadIcon, LoadingIcon } from "@/components/bs-icons/loading";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/bs-ui/dialog";
import { Textarea } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import Cascader from "@/components/bs-ui/select/cascader";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import Tip from "@/components/bs-ui/tooltip/tip";
import { getKnowledgeModelConfig, updateKnowledgeModelConfig } from "@/controllers/API/finetune";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { Settings } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
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


const PromptDialog = ({ value, onChange, onRestore, onSave, children }) => {
    const [open, setOpen] = useState(false)
    const modifyNotSavedRef = useRef(false)

    const handleCancel = () => {
        if (modifyNotSavedRef.current) {
            return bsConfirm({
                title: '取消修改',
                desc: "您的修改尚未保存，确定要退出吗？",
                onOk: (next) => {
                    next();
                    setOpen(false);
                    onRestore()
                    modifyNotSavedRef.current = false
                }
            })
        }
        setOpen(false);
    }

    return <Dialog open={open} onOpenChange={setOpen}>
        <DialogTrigger>
            {children}
        </DialogTrigger>
        <DialogContent close={false} className="sm:max-w-[625px] bg-background-login">
            <DialogHeader>
                <DialogTitle>编辑提示词</DialogTitle>
            </DialogHeader>
            <div>
                <Label className="bisheng-label">文档知识库摘要提示词</Label>
                <Textarea
                    value={value}
                    onChange={(e) => {
                        onChange(e);
                        modifyNotSavedRef.current = true;
                    }}
                    className="mt-1"
                    rows={16}
                />
            </div>
            <DialogFooter>
                <Button variant="outline" className="px-11" type="button" onClick={handleCancel}>取消</Button>
                <Button disabled={false} type="submit" className="px-11" onClick={() => {
                    modifyNotSavedRef.current = false
                    onSave()
                    setOpen(false)
                }}>
                    保存
                </Button>
            </DialogFooter>
        </DialogContent>
    </Dialog>
}

export default function KnowledgeModel({ llmOptions, embeddings, onBack }) {
    const { t } = useTranslation('model')

    const [form, setForm] = useState({
        embeddingModelId: null,
        sourceModelId: null,
        extractModelId: null,
        qaSimilarModelId: null,
        abstractPrompt: ''
    });
    // 最后保存的配置
    const lastSaveFormDataRef = useRef(null)

    const [loading, setLoading] = useState(true)
    useEffect(() => {
        setLoading(true)
        getKnowledgeModelConfig().then(config => {
            const { embedding_model_id, extract_title_model_id, qa_similar_model_id, source_model_id, abstract_prompt } = config
            setForm({
                embeddingModelId: embedding_model_id,
                sourceModelId: source_model_id,
                extractModelId: extract_title_model_id,
                qaSimilarModelId: qa_similar_model_id,
                abstractPrompt: abstract_prompt || defalutPrompt
            })
            lastSaveFormDataRef.current = { ...config, abstract_prompt: abstract_prompt || defalutPrompt }
            setLoading(false)
        });
    }, []);

    const { message } = useToast()
    const [saveload, setSaveLoad] = useState(false)
    const handleSave = async () => {
        const { embeddingModelId, extractModelId, qaSimilarModelId, sourceModelId, abstractPrompt } = form
        const errors = []
        if (!embeddingModelId) {
            errors.push(t('model.defaultEmbeddingModel') + t('bs:required'))
        }
        if (!qaSimilarModelId) {
            errors.push(t('model.qaSimilarModel') + t('bs:required'))
        }
        if (errors.length) return message({ variant: 'error', description: errors })

        const data = {
            embedding_model_id: embeddingModelId,
            extract_title_model_id: extractModelId,
            qa_similar_model_id: qaSimilarModelId,
            source_model_id: sourceModelId,
            abstract_prompt: abstractPrompt
        }
        setSaveLoad(true)
        await captureAndAlertRequestErrorHoc(updateKnowledgeModelConfig(data).then(res => {
            lastSaveFormDataRef.current = data
            message({ variant: 'success', description: t('model.saveSuccess') })
        }))
        setSaveLoad(false)
    };

    const handleSavePrompt = () => {
        captureAndAlertRequestErrorHoc(updateKnowledgeModelConfig({
            ...lastSaveFormDataRef.current,
            abstract_prompt: form.abstractPrompt
        }).then(res => {
            message({ variant: 'success', description: '提示词已保存' })
        }))
    }

    if (loading) return <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
        <LoadingIcon />
    </div>

    return (
        <div className="max-w-[520px] mx-auto gap-y-4 flex flex-col mt-16 relative">
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
            {/* 知识库摘要提示词编辑 */}
            <div className="absolute top-44 -right-28">
                <PromptDialog
                    value={form.abstractPrompt}
                    onChange={e => setForm({ ...form, abstractPrompt: e.target.value })}
                    onSave={handleSavePrompt}
                    onRestore={() => setForm({ ...form, abstractPrompt: lastSaveFormDataRef.current.abstract_prompt })}
                >
                    <Tip content={"文档知识库上传文件时，对文件进行摘要的提示词"} side={"top"}>
                        <Button variant="link"><Settings size={14} className="mr-1" /> 编辑提示词</Button>
                    </Tip>
                </PromptDialog>
            </div>
            <div className="mt-10 text-center space-x-6">
                <Button className="px-6" variant="outline" onClick={onBack}>{t('model.cancel')}</Button>
                <Button
                    className="px-10"
                    disabled={saveload}
                    onClick={handleSave}
                >
                    {saveload && <LoadIcon className="mr-2" />}
                    {t('model.save')}
                </Button>
            </div>
        </div>
    );
}


const defalutPrompt = `你是一名资深的“文档摘要专家”，能针对不同类型的文档（如报告、规章制度、合同、会议纪要、产品说明等）灵活调整摘要风格。
接下来你会收到一篇文档的主要内容，请按以下流程进行处理，并以 JSON 输出，方便后续程序化使用：
1. 文档识别（Type）  
   – 判断并简要说明这是哪种类型的文档及其主要目的（如“这是产品功能说明，用于向用户介绍 X 功能”）。

2. 关键信息（KeyInfo）  
   – 列出 3～7 条最重要的信息或论点，每条 10～20 字。（如有“重要条款”“核心决策”“关键日期”“行动项”等都写入）

3. 总体概述（Summary）  
   – 用 2～4 句话概括文档的核心内容和结论。

请严格按下面 JSON 模板输出（字段顺序和名称请保持一致）：

\`\`\`json
{
  "Type": "文档类型及目的说明",
  "KeyInfo": [
    "要点1",
    "要点2",
    "要点3"
  ],
  "Summary": "两到四句的总体概述……"
}
\`\`\``