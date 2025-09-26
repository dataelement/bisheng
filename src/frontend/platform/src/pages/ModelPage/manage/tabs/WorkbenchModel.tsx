import { LoadIcon, LoadingIcon } from "@/components/bs-icons/loading";
import { Button } from "@/components/bs-ui/button";
import { Label } from "@/components/bs-ui/label";
import Cascader from "@/components/bs-ui/select/cascader";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import { getLinsightModelConfig, updateLinsightModelConfig } from "@/controllers/API/finetune";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";


export const ModelSelect = ({ required = false, close = false, label, tooltipText = '', value, options, onChange }) => {
    const defaultValue = useMemo(() => {
        let _defaultValue = []
        if (!value || !options || options.length === 0) return _defaultValue

        const found = options.some(option => {
            const model = option.children?.find(el => el.value == value)
            if (model) {
                _defaultValue = [
                    { value: option.value, label: option.label },
                    { value: model.value, label: model.label }
                ]
                return true
            }
            return false
        })
        return _defaultValue
    }, [value, options])

    return (
        <div>
            <Label className="bisheng-label">
                <span>{label}</span>
                {required && <span className="text-red-500 text-xs">*</span>}
                {tooltipText && <QuestionTooltip className="relative top-0.5 ml-1" content={tooltipText}><span /></QuestionTooltip>}
            </Label>
            <Cascader
                key={`model-select-${value}-${options.length}`}
                defaultValue={defaultValue}
                options={options}
                close={close}
                onChange={(val) => onChange(val?.[1])}
            />
        </div>
    )
}

export default function WorkbenchModel({ llmOptions, embeddings, onBack }) {
    const { t } = useTranslation('model')
    const { message } = useToast()

    const [form, setForm] = useState({
        sourceModelId: null,
        extractModelId: null,
        executionMode: 'ReAct',
        asrModelId: null,
        ttsModelId: null
    });
    const lastSaveFormDataRef = useRef(null)
    const [loading, setLoading] = useState(true)
    const [saveload, setSaveLoad] = useState(false)

    const handleSave = async () => {
        const { extractModelId, sourceModelId, executionMode, asrModelId, ttsModelId } = form;
        const errors = [];
        if (errors.length) return message({ variant: 'error', description: errors });

        setSaveLoad(true);
        try {
            const data = {
                task_model: { id: String(extractModelId) },
                embedding_model: { id: String(sourceModelId) },
                linsight_executor_mode: executionMode,
                asr_model: { id: String(asrModelId) },
                tts_model: { id: String(ttsModelId) }
            };

            await captureAndAlertRequestErrorHoc(updateLinsightModelConfig(data))
            const linsightConfig = await captureAndAlertRequestErrorHoc(getLinsightModelConfig())

            setForm({
                sourceModelId: linsightConfig?.embedding_model?.id || null,
                extractModelId: linsightConfig?.task_model?.id || null,
                executionMode: linsightConfig?.linsight_executor_mode || 'ReAct',
                asrModelId: linsightConfig?.asr_model?.id || null,
                ttsModelId: linsightConfig?.tts_model?.id || null
            });

            lastSaveFormDataRef.current = {
                task_model: { id: linsightConfig?.task_model?.id },
                embedding_model: { id: linsightConfig?.embedding_model?.id },
                linsight_executor_mode: linsightConfig?.linsight_executor_mode || 'ReAct',
                abstract_prompt: linsightConfig?.abstract_prompt || defalutPrompt,
                asr_model: { id: linsightConfig?.asr_model?.id },
                tts_model: { id: linsightConfig?.tts_model?.id }
            };
        } finally {
            setSaveLoad(false);
        }
    };

    // 检查是否修改了 embedding 模型
    const checkEmbeddingModified = () => {
        const lastEmbeddingId = lastSaveFormDataRef.current?.embedding_model?.id;
        const currentEmbeddingId = form.sourceModelId;
        return lastEmbeddingId !== currentEmbeddingId;
    };

    const handleSaveWithConfirm = () => {
        if (checkEmbeddingModified()) {
            bsConfirm({
                title: '提示',
                desc: '修改 embedding 模型可能会消耗大量模型资源且耗时较久，确认修改？',
                showClose: true,
                okTxt: '确认',
                canelTxt: '取消',
                onOk(next) {
                    handleSave().then(next);
                },
                onCancel() { }
            });
        } else {
            handleSave();
        }
    };

    useEffect(() => {
        setLoading(true);

        getLinsightModelConfig()
            .then(linsightConfig => {
                const safeLinsightConfig = linsightConfig || {
                    task_model: null,
                    embedding_model: null,
                    abstract_prompt: defalutPrompt,
                    linsight_executor_mode: 'ReAct', // 默认执行模式
                };

                setForm({
                    sourceModelId: safeLinsightConfig.embedding_model?.id || null,
                    extractModelId: safeLinsightConfig.task_model?.id || null,
                    executionMode: safeLinsightConfig.linsight_executor_mode || 'ReAct',
                    asrModelId: safeLinsightConfig.asr_model?.id || null,
                    ttsModelId: safeLinsightConfig.tts_model?.id || null
                });

                lastSaveFormDataRef.current = {
                    task_model: { id: safeLinsightConfig.task_model?.id },
                    embedding_model: {
                        id: safeLinsightConfig.embedding_model?.id
                    },
                    linsight_executor_mode: safeLinsightConfig.linsight_executor_mode || 'ReAct',
                    abstract_prompt: safeLinsightConfig.abstract_prompt || defalutPrompt,
                    asr_model: { id: safeLinsightConfig.asr_model?.id },
                    tts_model: { id: safeLinsightConfig.tts_model?.id }
                };

                setLoading(false);
            })
            .catch(error => {
                console.error('获取配置失败:', error);
                setLoading(false);
                message({ variant: 'error', description: '获取配置失败' });
            });
    }, []);

    if (loading) return <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
        <LoadingIcon />
    </div>

    return (
        <div className="max-w-[520px] mx-auto gap-y-4 flex flex-col mt-16 relative">
            <ModelSelect
                close
                label={t('model.workVectorModel')}
                tooltipText={t('model.workVectorModelTooltip')}
                value={form.sourceModelId}
                options={embeddings}
                onChange={(val) => setForm({ ...form, sourceModelId: val })}
            />
            <h3 className="bisheng-label">{t('model.lingsiTaskModel')}</h3>
            <div className="border rounded-lg p-4 -mt-3">
                <div className="flex gap-4">
                    <div className="flex-1">
                        <ModelSelect
                            close
                            label={t('model.model')}
                            tooltipText={t('model.lingsiTaskModelTooltip')}
                            value={form.extractModelId}
                            options={llmOptions}
                            onChange={(val) => setForm({ ...form, extractModelId: val })}
                        />
                    </div>
                    <div className="flex-1">
                        <Label className="bisheng-label">
                            <span>{t('model.executionMode')}</span>
                            <QuestionTooltip className="relative top-0.5 ml-1" content="一般情况可选择 function call 模式，模型不支持 function call 或追求最佳任务执行效果时可选择 ReAct 模式"><span /></QuestionTooltip>
                        </Label>
                        <Select
                            value={form.executionMode}
                            onValueChange={(val) => setForm({ ...form, executionMode: val })}
                        >
                            <SelectTrigger className="w-full">
                                <SelectValue placeholder="选择执行模式" />
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value="func_call">Function Call</SelectItem>
                                <SelectItem value="react">ReAct</SelectItem>
                            </SelectContent>
                        </Select>
                    </div>
                </div>
            </div>
            <h3 className="bisheng-label">{t('工作台语音模型')}</h3>
            <div className="border rounded-lg p-4 -mt-3">
         
                        <ModelSelect
                            close
                            label={t('语音转文字（ASR）模型')}
                            tooltipText={t('用于工作台\\应用的语音转文字场景')}
                            value={form.asrModelId}
                            options={llmOptions}
                            onChange={(val) => setForm({ ...form, asrModelId: val })}
                        />
                 
                
                        <ModelSelect
                            close
                            label={t('文字转语音（TTS）模型')}
                            tooltipText={t('用于工作台\\应用的文字转语音场景')}
                            value={form.ttsModelId}
                            options={llmOptions}
                            onChange={(val) => setForm({ ...form, ttsModelId: val })}
                        />
                 
             
            </div>

            <div className="mt-10 text-center space-x-6">
                <Button className="px-6" variant="outline" onClick={onBack}>{t('model.cancel')}</Button>
                <Button
                    className="px-10"
                    disabled={saveload}
                    onClick={handleSaveWithConfirm}
                >
                    {saveload && <LoadIcon className="mr-2" />}
                    {t('model.save')}
                </Button>
            </div>
        </div>
    );
}

export const defalutPrompt = `# role
你是一名经验丰富的“文档摘要专家”，擅长针对不同类型的文档（例如：书籍、论文、标书、研究报告、规章制度、合同协议、会议纪要、产品手册、运维手册、需求说明书等）进行精准识别，并根据文档类型灵活调整摘要风格，例如：
- 报告类文档需强调研究发现或核心观点；
- 制度类文档需突出制度目的及适用范围；
- 合同类文档需明确合同主体及关键条款；
- 会议纪要需聚焦会议议题与决策结果；
- 产品说明需提炼产品功能与使用场景。

# task
接下来你将收到一篇文档的主要内容，请你：
1. 判断并简要说明该文档属于上述哪种类型；
2. 使用2～3句话概括文档的核心内容和关键结论，强调信息的准确性、完整性与清晰度。

# result example
【文档类型】：会议纪要  
【摘要】：本文档为公司季度业务会议纪要，会议围绕本季度销售目标的达成情况展开，最终决定下一季度加强市场推广投入，并设立专门团队负责新产品上市工作，以改善销售表现。`