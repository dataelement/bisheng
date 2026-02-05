// src/features/chat-config/components/ModelManagement.tsx
import { TrashIcon } from "@/components/bs-icons";
import { Button } from "@/components/bs-ui/button";
import { Checkbox } from "@/components/bs-ui/checkBox";
import { Input } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { Switch } from "@/components/bs-ui/switch";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import { useModel } from "@/pages/ModelPage/manage";
import { ModelSelect } from "@/pages/ModelPage/manage/tabs/KnowledgeModel";
import { Check, Plus } from "lucide-react";
import { forwardRef } from "react";
import { useTranslation } from "react-i18next";

export interface Model {
    key: string;
    id: string;
    name: string;
    displayName: string;
    visual?: boolean;
}
interface ModelManagementProps {
    models: Model[];
    errors: string[][];
    error: string;
    onAdd: () => void;
    onRemove: (index: number) => void;
    onModelChange: (index: number, id: string) => void;
    onNameChange: (index: number, name: string) => void;
    onVisualToggle?: (index: number, enabled: boolean) => void;
}
export const ModelManagement = forwardRef<HTMLDivElement[], ModelManagementProps>(
    ({ models, errors, error, onAdd, onRemove, onModelChange, onNameChange, onVisualToggle }, ref) => {
        const { llmOptions } = useModel();
        const { t } = useTranslation();

        // Bind ref to each model item
        const setItemRef = (el: HTMLDivElement | null, index: number) => {
            const refs = ref as React.MutableRefObject<(HTMLDivElement | null)[]>;
            if (refs.current) {
                refs.current[index] = el;
            }
        };

        // useEffect(() => {
        // If the model list is empty, automatically add a model
        // models.forEach((model, index) => {
        //     !model.id && llmOptions.length && onModelChange(index, llmOptions[0].children[0].value)
        // })
        // }, [models, llmOptions])

        return (
            <div className="mt-2 border p-4 rounded-md bg-muted">
                <div className="grid mb-4 items-center" style={{ gridTemplateColumns: "1fr 1fr 120px 60px" }}>
                    <div className="">
                        <Label className="bisheng-label">{t('bench.model')}</Label>
                    </div>
                    <div className="">
                        <Label className="bisheng-label">{t('bench.displayName')}</Label>
                    </div>
                    <div className="flex items-center justify-center">
                        <Label className="bisheng-label whitespace-nowrap mr-0.5">{t('bench.vision')}</Label>
                        <QuestionTooltip className="text-[#999999]" content={t('bench.visionText')} />
                    </div>
                    <div className="text-center">
                    </div>
                </div>

                {models.map((model, index) => (
                    <div key={model.key} className="grid items-center mb-4" style={{ gridTemplateColumns: "1fr 1fr 120px 60px" }}>
                        <div className="pr-2" id={model.id}>
                            {llmOptions.length > 0 ? (
                                <ModelSelect
                                    key={model.id}
                                    label={''}
                                    value={model.id}
                                    options={llmOptions}
                                    onChange={(val) => onModelChange(index, val)}
                                />
                            ) : (
                                <ModelSelect
                                    key={'model.id'}
                                    label={''}
                                    value={''}
                                    options={[]}
                                    onChange={(val) => { }}
                                />
                            )}
                            {errors[model.key] && <p className="text-red-500 text-xs mt-1">{errors[model.key]?.[0]}</p>}
                        </div>
                        <div className="pr-2">
                            <Input
                                value={model.displayName}
                                onChange={(e) => onNameChange(index, e.target.value)}
                                placeholder={t('bench.displayName')}
                            />
                            {errors[model.key] && <p className="text-red-500 text-xs mt-1">{errors[model.key]?.[1]}</p>}
                        </div>

                        <div className="flex items-center justify-center">
                            <Checkbox
                                checked={model.visual || false}
                                onCheckedChange={(checked) => {
                                    if (onVisualToggle) {
                                        onVisualToggle(index, checked);
                                    }
                                }}
                            />
                        </div>

                        {/* 删除按钮 */}
                        <div className="flex items-center justify-center">
                            <TrashIcon
                                className="text-gray-500 cursor-pointer size-4 hover:text-red-500 transition-colors"
                                onClick={() => onRemove(index)}
                            />
                        </div>
                    </div>
                ))}

                <Button
                    variant="outline"
                    className="border-none size-7 bg-gray-200 hover:bg-gray-300 transition-colors mt-2"
                    size="icon"
                    onClick={onAdd}
                >
                    <Plus className="size-5" />
                </Button>

                {error && <p className="text-red-500 text-xs mt-1">{error}</p>}
            </div>
        );

    }
)
ModelManagement.displayName = "ModelManagement"