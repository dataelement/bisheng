import { LoadIcon, LoadingIcon } from "@/components/bs-icons/loading";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Button } from "@/components/bs-ui/button";
import { Label } from "@/components/bs-ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";
import Cascader from "@/components/bs-ui/select/cascader";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import { getLinsightModelConfig, updateLinsightModelConfig } from "@/controllers/API/finetune";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "react-query";
import { useModel } from "..";

export const ModelSelect = ({ required = false, close = false, label, tooltipText = '', value, options, onChange,placeholder = '' }) => {
    const defaultValue = useMemo(() => {
        let _defaultValue = []
        if (!value || !options || options.length === 0) return _defaultValue

        options.forEach(option => {
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
                {tooltipText && <QuestionTooltip className="relative top-0.5 ml-1" content={tooltipText}></QuestionTooltip>}
            </Label>
            <Cascader
                key={`model-select-${value}-${options.length}`}
                defaultValue={defaultValue}
                options={options}
                close={close}
                onChange={(val) => onChange(val?.[1])}
                placeholder={placeholder}
            />
        </div>
    )
}

export default function WorkbenchModel({ onBack }) {
    const { llmOptions, embeddings, asrModel, ttsModel } = useModel();
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
    const [saveload, setSaveLoad] = useState(false)

    const { data: linsightConfig, isLoading: loading, refetch: refetchConfig, error } = useLinsightConfig();

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
                asr_model: asrModelId ? { id: String(asrModelId) } : null, // 支持空值
                tts_model: ttsModelId ? { id: String(ttsModelId) } : null
            };

            // 提交更新并通过 refetch 获取最新配置（无需再次调用 getLinsightModelConfig）
            const response = await captureAndAlertRequestErrorHoc(updateLinsightModelConfig(data));
            const updatedConfig = await refetchConfig();

            // 直接使用 refetch 返回的最新数据更新状态
            const newConfig = updatedConfig.data;
            setForm({
                sourceModelId: newConfig?.embedding_model?.id || null,
                extractModelId: newConfig?.task_model?.id || null,
                executionMode: newConfig?.linsight_executor_mode || 'ReAct',
                asrModelId: newConfig?.asr_model?.id || null,
                ttsModelId: newConfig?.tts_model?.id || null
            });

            lastSaveFormDataRef.current = {
                task_model: { id: newConfig?.task_model?.id },
                embedding_model: { id: newConfig?.embedding_model?.id },
                linsight_executor_mode: newConfig?.linsight_executor_mode || 'ReAct',
                abstract_prompt: newConfig?.abstract_prompt || defalutPrompt,
                asr_model: { id: newConfig?.asr_model?.id },
                tts_model: { id: newConfig?.tts_model?.id }
            };
            if(response !== false){
                message({ variant: 'success', description: t('model.saveSuccess') });
            }
        } catch (err) {
            message({ variant: 'error', description: t('model.saveFailed') });
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
                title: t('model.tip'),
                desc: t('model.confirmEmbeddingChange'),
                showClose: true,
                okTxt: t('model.confirm'),
                canelTxt: t('model.cancel'),
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
        if (error) {
            message({ variant: 'error', description: t('model.fetchConfigFailed') });
            return;
        }

        // 2. 配置数据就绪后，更新表单和缓存（添加 defalutPrompt 到依赖）
        if (linsightConfig) {
            setForm({
                sourceModelId: linsightConfig.embedding_model?.id || null,
                extractModelId: linsightConfig.task_model?.id || null,
                executionMode: linsightConfig.linsight_executor_mode || 'ReAct',
                asrModelId: linsightConfig.asr_model?.id || null,
                ttsModelId: linsightConfig.tts_model?.id || null
            });

            lastSaveFormDataRef.current = {
                task_model: { id: linsightConfig.task_model?.id },
                embedding_model: { id: linsightConfig.embedding_model?.id },
                linsight_executor_mode: linsightConfig.linsight_executor_mode || 'ReAct',
                abstract_prompt: linsightConfig.abstract_prompt || defalutPrompt,
                asr_model: { id: linsightConfig.asr_model?.id },
                tts_model: { id: linsightConfig.tts_model?.id }
            };
        }
    }, [linsightConfig, error, message, defalutPrompt, t]);

    if (loading) return (
        <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
            <LoadingIcon />
        </div>
    );
    console.log('ASR Model Options structure:', JSON.stringify(asrModel, null, 2));
    console.log('TTS Model Options structure:', JSON.stringify(ttsModel, null, 2));
    return (
        <div className="max-w-[520px] mx-auto gap-y-4 flex flex-col mt-16 relative">
            <ModelSelect
                close
                label={t('model.workVectorModel')}
                tooltipText={t('model.workVectorModelTooltip')}
                value={form.sourceModelId}
                options={embeddings}
                onChange={(val) => setForm({ ...form, sourceModelId: val })}
                required
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
                            required
                        />
                    </div>
                    <div className="flex-1">
                        <Label className="bisheng-label">
                            <span>{t('model.executionMode')}</span>
                            <QuestionTooltip className="relative top-0.5 ml-1" content={t('model.executionModeTooltip')}></QuestionTooltip>
                        </Label>
                        <Select
                            value={form.executionMode}
                            onValueChange={(val) => setForm({ ...form, executionMode: val })}
                        >
                            <SelectTrigger className="w-full">
                                <SelectValue placeholder={t('model.selectExecutionMode')} />
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value="func_call">{t('model.functionCall')}</SelectItem>
                                <SelectItem value="react">{t('model.react')}</SelectItem>
                            </SelectContent>
                        </Select>
                    </div>
                </div>
            </div>
            <h3 className="bisheng-label">{t('model.workbenchVoiceModel')}</h3>
            <div className="border rounded-lg p-4 -mt-3 space-y-4">
                <ModelSelect
                    close
                    label={t('model.asrModel')}
                    tooltipText={t('model.asrModelTooltip')}
                    value={form.asrModelId}
                    options={asrModel}
                    onChange={(val) => setForm({ ...form, asrModelId: val })}
                />
                <ModelSelect
                    close
                    label={t('model.ttsModel')}
                    tooltipText={t('model.ttsModelTooltip')}
                    value={form.ttsModelId}
                    options={ttsModel}
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

export function useLinsightConfig() {
    return useQuery({
        queryKey: ["linsightModelConfig"],
        queryFn: () => captureAndAlertRequestErrorHoc(getLinsightModelConfig()),
        select: (data) => {
            const safeConfig = data || {
                task_model: null,
                embedding_model: null,
                abstract_prompt: defalutPrompt,
                linsight_executor_mode: "ReAct",
                asr_model: null,
                tts_model: null,
            };
            return safeConfig;
        },
        retry: 1,
    });
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
【摘要】：本文档为公司季度业务会议纪要，会议围绕本季度销售目标的达成情况展开，最终决定下一季度加强市场推广投入，并设立专门团队负责新产品上市工作，以改善销售表现。`;