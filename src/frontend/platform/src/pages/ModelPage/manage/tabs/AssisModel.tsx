import { TrashIcon } from "@/components/bs-icons";
import { Button } from "@/components/bs-ui/button";
import { Input } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import { generateUUID } from "@/components/bs-ui/utils";
import { RadioGroup, RadioGroupItem } from "@/components/bs-ui/radio-group";
import { getAssistantModelConfig, updateAssistantModelConfig } from "@/controllers/API/finetune";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import uniqBy from "lodash-es/uniqBy";
import { Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ModelSelect } from "./KnowledgeModel";
import { LoadingIcon } from "@/components/bs-icons/loading";


const ModelRow = ({ item, index, llmOptions, updateField, deleteRow }) => {
    const { t } = useTranslation('model')

    return <div className="grid mb-4 items-center" style={{ gridTemplateColumns: "repeat(2, 1fr) 80px 110px 76px 90px 40px" }}>
        <div className="pr-2">
            <ModelSelect
                label={''}
                value={item.model_id}
                options={llmOptions}
                onChange={(val) => updateField(index, 'model_id', val)}
            />
        </div>
        <div className="pr-2">
            <Select value={item.agent_executor_type} onValueChange={(val) => updateField(index, 'agent_executor_type', val)}>
                <SelectTrigger>
                    <SelectValue placeholder="" />
                </SelectTrigger>
                <SelectContent>
                    <SelectGroup>
                        <SelectItem value="function call">Function call</SelectItem>
                        <SelectItem value="ReAct">ReAct</SelectItem>
                    </SelectGroup>
                </SelectContent>
            </Select>
        </div>
        <div className="pr-2">
            <Select value={item.streaming ? "1" : "0"} onValueChange={(val) => updateField(index, 'streaming', val === "1")}>
                <SelectTrigger>
                    <SelectValue placeholder="" />
                </SelectTrigger>
                <SelectContent>
                    <SelectGroup>
                        <SelectItem value="1">{t('model.yes')}</SelectItem>
                        <SelectItem value="0">{t('model.no')}</SelectItem>
                    </SelectGroup>
                </SelectContent>
            </Select>
        </div>
        <div className="pr-2">
            <Input
                type="number"
                value={item.knowledge_max_content}
                onChange={(e) => updateField(index, 'knowledge_max_content', Math.min(parseInt(e.target.value), 15000))}
                min={1}
                max={15000}
            />
        </div>
        <div className="pr-2">
            <Select value={item.knowledge_sort_index ? "1" : "0"} onValueChange={(val) => updateField(index, 'knowledge_sort_index', val === "1")}>
                <SelectTrigger>
                    <SelectValue placeholder="" />
                </SelectTrigger>
                <SelectContent>
                    <SelectGroup>
                        <SelectItem value="1">{t('model.yes')}</SelectItem>
                        <SelectItem value="0">{t('model.no')}</SelectItem>
                    </SelectGroup>
                </SelectContent>
            </Select>
        </div>
        <div className="m-auto">
            <RadioGroup value={item.default ? "1" : "0"} onValueChange={(val) => updateField(index, 'default', val === "1")}>
                <RadioGroupItem value="1"></RadioGroupItem>
            </RadioGroup>
        </div>
        <div className="m-auto">
            <TrashIcon className="text-gray-500 cursor-pointer size-4" onClick={() => deleteRow(index)} />
        </div>
    </div>
};

const defaultValue = {
    llm_list: [{
        model_id: null,
        agent_executor_type: "",
        knowledge_max_content: 15000,
        knowledge_sort_index: false,
        default: true,
        streaming: false
    }],
    auto_llm: {
        model_id: null,
        agent_executor_type: "",
        knowledge_max_content: 0,
        knowledge_sort_index: false,
        default: false,
        streaming: false
    }
}

export default function AssisModel({ llmOptions, onBack }) {
    const [form, setForm] = useState({ ...defaultValue });
    const { t } = useTranslation('model')

    const [loading, setLoading] = useState(true)
    useEffect(() => {
        setLoading(true)
        getAssistantModelConfig().then(({ llm_list, auto_llm }) => {
            setForm({
                llm_list,
                auto_llm: auto_llm || { ...defaultValue.auto_llm }
            })
            setLoading(false)
        })
    }, []);

    const updateField = (index, field, value) => {
        const updatedList = form.llm_list.map((item, i) => {
            if (i === index) {
                return { ...item, [field]: value };
            } else if (field === 'default' && value === true) {
                return { ...item, default: false };
            }
            return item;
        });

        setForm({ ...form, llm_list: updatedList });
    };

    const updateAutoLLMField = (field, value) => {
        setForm({ ...form, auto_llm: { ...form.auto_llm, [field]: value } });
    };

    const addNewRow = () => {
        const newRow = {
            model_id: Date.now(),
            agent_executor_type: "",
            knowledge_max_content: 15000,
            knowledge_sort_index: false,
            default: !form.llm_list.length,
            streaming: true
        };
        setForm({
            ...form,
            llm_list: [...form.llm_list, newRow]
        });
    };

    const deleteRow = (index) => {
        let target = null
        const updatedList = form.llm_list.filter((_, i) => {
            if (i === index) {
                target = _
                return false
            }
            return true
        }).map((item, i) => {
            if (target.default && i === 0) return { ...item, default: true };
            return item;
        });
        setForm({ ...form, llm_list: updatedList });
    };

    const { message } = useToast()
    const handleSave = () => {
        console.log('Form data to save:', form);
        if (form.llm_list.some(el => el.model_id === null)) {
            return message({ variant: 'error', description: t('model.assistantInferenceModel') + t('bs:required') })
        }
        if (form.auto_llm.model_id === null) {
            return message({ variant: 'error', description: t('model.assistantAutoOptimizationModel') + t('bs:required') })
        }
        const uniqueList = uniqBy(form.llm_list, 'model_id');
        if (uniqueList.length !== form.llm_list.length) {
            return message({ variant: 'error', description: t('model.assistantInferenceModelRepetition') })
        }

        captureAndAlertRequestErrorHoc(updateAssistantModelConfig(form).then(res => {
            message({ variant: 'success', description: t('model.saveSuccess') })
        }));
    };

    if (loading) return <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
        <LoadingIcon />
    </div>

    return (
        <div className="w-[70vw] mx-auto pt-2">
            <div className="mb-6">
                <span className="pl-1">{t('model.assistantInferenceModel')}</span>
                <div className="mt-2 border p-4 rounded-md bg-muted">
                    <div className="grid mb-4 items-center" style={{ gridTemplateColumns: "repeat(2, 1fr) 80px 110px 68px 90px 40px" }}>
                        <Label className="bisheng-label">{t('model.model')}<span className="text-red-500 text-xs">*</span></Label>
                        <Label className="bisheng-label">
                            <span>{t('model.assistantExecutionMode')}</span>
                            <QuestionTooltip className="relative top-0.5 ml-1" content={t('model.assistantExecutionModeTooltip')} />
                        </Label>
                        <Label className="bisheng-label">{t('model.streamingOutput')}</Label>
                        <Label className="bisheng-label">
                            <span>{t('model.assistantKnowledgeBaseMaxCharacters')}</span>
                            <QuestionTooltip className="relative top-0.5 ml-1" content={t('model.assistantKnowledgeBaseMaxCharactersTooltip')} />
                        </Label>
                        <Label className="bisheng-label">
                            <span>{t('model.reorderAfterRetrieval')}</span>
                            <QuestionTooltip className="relative top-0.5 ml-1" content={t('model.reorderAfterRetrievalTooltip')} />
                        </Label>
                        <Label className="bisheng-label text-center">{t('model.setAsDefault')}</Label>
                        <div></div>
                    </div>
                    {form.llm_list.map((item, index) => (
                        <ModelRow
                            key={generateUUID(6)} // more render
                            item={item}
                            index={index}
                            llmOptions={llmOptions}
                            updateField={updateField}
                            deleteRow={deleteRow}
                        />
                    ))}
                    <Button variant="outline" size="icon" onClick={addNewRow}>
                        <Plus className="size-5" />
                    </Button>
                </div>
            </div>
            <div className="">
                <span className="pl-1">{t('model.assistantAutoOptimizationModel')}</span>
                <div className="mt-2 border p-4 rounded-md bg-muted">
                    <div className="grid grid-cols-4 gap-2">
                        <Label className="bisheng-label">{t('model.model')}<span className="text-red-500 text-xs">*</span></Label>
                        <Label className="bisheng-label">{t('model.streamingOutput')}</Label>
                    </div>
                    <div className="grid grid-cols-4 gap-2 mt-4">
                        <ModelSelect
                            label={''}
                            value={form.auto_llm.model_id}
                            options={llmOptions}
                            onChange={(val) => updateAutoLLMField('model_id', val)}
                        />
                        <Select value={form.auto_llm.streaming ? "1" : "0"} onValueChange={(val) => updateAutoLLMField('streaming', val === "1")}>
                            <SelectTrigger>
                                <SelectValue placeholder="" />
                            </SelectTrigger>
                            <SelectContent>
                                <SelectGroup>
                                    <SelectItem value="1">{t('model.yes')}</SelectItem>
                                    <SelectItem value="0">{t('model.no')}</SelectItem>
                                </SelectGroup>
                            </SelectContent>
                        </Select>
                    </div>
                </div>
            </div>
            <div className="mt-10 text-center space-x-6">
                <Button className="px-6" variant="outline" onClick={onBack}>{t('model.cancel')}</Button>
                <Button className="px-10" onClick={handleSave}>{t('model.save')}</Button>
            </div>
        </div>
    );
}
