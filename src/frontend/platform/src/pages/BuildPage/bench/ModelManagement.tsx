// src/features/chat-config/components/ModelManagement.tsx
import { TrashIcon } from "@/components/bs-icons";
import { Button } from "@/components/bs-ui/button";
import { Input } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { useAssistantLLmModel } from "@/pages/ModelPage/manage";
import { ModelSelect } from "@/pages/ModelPage/manage/tabs/KnowledgeModel";
import { Plus } from "lucide-react";
import { useEffect } from "react";

export interface Model {
    key: string;
    id: string;
    name: string;
    displayName: string;
}

export const ModelManagement = ({
    models,
    errors,
    error,
    onAdd,
    onRemove,
    onModelChange,
    onNameChange,
}: {
    models: Model[];
    error: string;
    errors: string[][];
    onAdd: () => void;
    onRemove: (index: number) => void;
    onModelChange: (index: number, id: string) => void;
    onNameChange: (index: number, name: string) => void;
}) => {
    const { llmOptions } = useAssistantLLmModel()

    // useEffect(() => {
    // 如果模型列表为空，则自动添加一个模型
    // models.forEach((model, index) => {
    //     !model.id && llmOptions.length && onModelChange(index, llmOptions[0].children[0].value)
    // })
    // }, [models, llmOptions])

    return <div className="mt-2 border p-4 rounded-md bg-muted">
        <div className="grid mb-4 items-center" style={{ gridTemplateColumns: "repeat(2, 1fr) 40px" }}>
            <Label className="bisheng-label">模型</Label>
            <Label className="bisheng-label">显示名称</Label>
            <div></div>
        </div>
        {models.map((model, index) => (
            <div key={model.key} className="grid mb-4 items-start"
                style={{ gridTemplateColumns: "repeat(2, 1fr) 40px" }}>
                <div className="pr-2" id={model.id}>
                    {llmOptions.length > 0 ? <ModelSelect
                        key={model.id}
                        label={''}
                        value={model.id}
                        options={llmOptions}
                        onChange={(val) => onModelChange(index, val)}
                    /> : <ModelSelect
                        key={'model.id'}
                        label={''}
                        value={''}
                        options={[]}
                        onChange={(val) => {}}
                    />}
                    {errors[model.key] && <p className="text-red-500 text-xs mt-1">{errors[model.key]?.[0]}</p>}
                </div>
                <div className="pr-2">
                    <Input
                        value={model.displayName}
                        onChange={(e) => onNameChange(index, e.target.value)}
                        placeholder="显示名称"
                    />
                    {errors[model.key] && <p className="text-red-500 text-xs mt-1">{errors[model.key]?.[1]}</p>}
                </div>
                <div className="m-auto">
                    <TrashIcon
                        className="text-gray-500 cursor-pointer size-4"
                        onClick={() => onRemove(index)}
                    />
                </div>
            </div>
        ))}
        <Button variant="outline" className="border-none size-7 bg-gray-200" size="icon" onClick={onAdd}>
            <Plus className="size-5" />
        </Button>
        {error && <p className="text-red-500 text-xs mt-1">{error}</p>}
    </div>
};