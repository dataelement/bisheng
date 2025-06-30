import { LoadIcon, LoadingIcon } from "@/components/bs-icons/loading";
import { Button } from "@/components/bs-ui/button";
import { Label } from "@/components/bs-ui/label";
import Cascader from "@/components/bs-ui/select/cascader";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import { getKnowledgeModelConfig, getLinsightModelConfig, updateLinsightModelConfig } from "@/controllers/API/finetune";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { getWorkstationConfigApi} from "@/controllers/API";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

export const ModelSelect = ({ required = false, close = false, label, tooltipText = '', value, options, onChange }) => {
    const defaultValue = useMemo(() => {
        let _defaultValue = []
        if (!value) return _defaultValue
        
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
        // 移除自动清空逻辑
        return _defaultValue
    }, [value, options])

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
                onChange={(val) => onChange(val?.[1])}
            />
        </div>
    )
}


export default function WorkbenchModel({ llmOptions, embeddings, onBack }) {
    const { t } = useTranslation('model')

    const [form, setForm] = useState({
     
        sourceModelId: null,
        extractModelId: null,
        qaSimilarModelId: null,
       
    });
    // 最后保存的配置
    const lastSaveFormDataRef = useRef(null)



    const [loading, setLoading] = useState(true)
//     useEffect(() => {
//         setLoading(true)
//       getLinsightModelConfig().then(config => {
    
//     // 直接从响应对象解构，而不是config.data
//     const { 
//         task_model, 
//         task_summary_model, 
//         sop_embedding_model 
//     } = config;
    
    
//     setForm({
//         sourceModelId: sop_embedding_model?.id || null,
//         extractModelId:  task_model?.id || null,
//         qaSimilarModelId: task_summary_model?.id || null,
//     })

//     lastSaveFormDataRef.current = {
//         task_model: { id: task_model?.id },
//         task_summary_model: { id: task_summary_model?.id },
//         sop_embedding_model: { id: sop_embedding_model?.id },
//         abstract_prompt: config.abstract_prompt || defalutPrompt
//     };
    
//     setLoading(false);
// }).catch(error => {
//     console.error('获取配置失败:', error);
//     setLoading(false);
//     message({ variant: 'error', description: '获取配置失败' });
// });
//     }, []);

    const { message } = useToast()
    const [saveload, setSaveLoad] = useState(false)
    const handleSave = async () => {
        const { extractModelId, qaSimilarModelId, sourceModelId,} = form
        const errors = []
        if (!qaSimilarModelId) {
            errors.push(t('model.qaSimilarModel') + t('bs:required'))
        }
        if (errors.length) return message({ variant: 'error', description: errors })

        const data = {
            extract_title_model_id: extractModelId,
            qa_similar_model_id: qaSimilarModelId,
            source_model_id: sourceModelId,
        }
        setSaveLoad(true)
        await captureAndAlertRequestErrorHoc(updateLinsightModelConfig(data).then(res => {
            lastSaveFormDataRef.current = data
            message({ variant: 'success', description: t('model.saveSuccess') })
        }))
        setSaveLoad(false)
    };
useEffect(() => {
    setLoading(true);
    
    // 并行获取三个配置
    Promise.all([
        getLinsightModelConfig(),
        getWorkstationConfigApi(),
        getKnowledgeModelConfig()
    ])
    .then(([linsightConfig, workstationConfig, knowledgeConfig]) => {
        // 确定 extractModelId 的优先级
        const extractModelId = 
            workstationConfig.models?.[0]?.id || 
            linsightConfig.task_model?.id || 
            null;
        const sourceModelId = 
            linsightConfig.sop_embedding_model?.id || 
            knowledgeConfig.embedding_model_id || 
            null;

        setForm({
            sourceModelId,
            extractModelId: linsightConfig.task_model?.id || extractModelId,
            qaSimilarModelId: linsightConfig.task_summary_model?.id || null,
        });

        lastSaveFormDataRef.current = {
            task_model: { id: linsightConfig.task_model?.id },
            task_summary_model: { id: linsightConfig.task_summary_model?.id },
            sop_embedding_model: { id: sourceModelId },
            abstract_prompt: linsightConfig.abstract_prompt || defalutPrompt
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
                label={t('model.workInformationModel')}
                tooltipText={t('model.workInformationModelTooltip')}
                value={form.extractModelId}
                options={llmOptions}
                onChange={(val) => setForm({ ...form, extractModelId: val })}
            />
            <ModelSelect
                close
                label={t('model.workVectorModel')}
                tooltipText={t('model.workVectorModelTooltip')}
                value={form.sourceModelId}
                options={embeddings}
                onChange={(val) => setForm({ ...form, sourceModelId: val })}
            />
           
            <ModelSelect
                close
                label={t('model.lingsiTaskModel')}
                tooltipText={t('model.lingsiTaskModelTooltip')}
                value={form.qaSimilarModelId}
                options={llmOptions}
                onChange={(val) => setForm({ ...form, qaSimilarModelId: val })}
                
            />
            
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
1. 总体概述（Summary）  
   – 判断并简要说明这是哪种类型的文档，用 2～3 句话概括文档的核心内容和结论（例如“这是产品功能说明，用于向用户介绍 X 功能……”）。

2. 关键信息（KeyInfo）  
   – 列出 3 条最重要的信息或论点，每条 10～20 字。

请严格按下面 JSON 模板输出（字段顺序和名称请保持一致）：

\`\`\`json
{{
  "Summary": "2～3句的总体概述……",
  "KeyInfo": [
    "要点1",
    "要点2",
    "要点3"
  ]
}}
\`\`\``