// src/features/chat-config/components/ModelManagement.tsx
import { TrashIcon } from "@/components/bs-icons";
import { Button } from "@/components/bs-ui/button";
import { Input } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { Switch } from "@/components/bs-ui/switch";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import { useModel } from "@/pages/ModelPage/manage";
import { ModelSelect } from "@/pages/ModelPage/manage/tabs/KnowledgeModel";
import { Plus } from "lucide-react";
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

        return (<div className="mt-2 border p-4 rounded-md bg-muted">
            <div className="grid mb-4 items-center" style={{ gridTemplateColumns: "repeat(2, 1fr) 80px 40px" }}>
                <Label className="bisheng-label">{t('bench.model')}</Label>
                <Label className="bisheng-label">{t('bench.displayName')}</Label>
                <div></div>
                <div className="flex">
                    <Label className="bisheng-label  whitespace-nowrap">{t('bench.vision')}</Label>
                    <QuestionTooltip content={t('bench.visionText')} />
                </div>
            </div>
            {models.map((model, index) => (
                <div key={model.key} className="grid mb-4 items-start"
                    style={{ gridTemplateColumns: "repeat(2, 1fr) 80px 40px" }}
                    ref={el => setItemRef(el, index)}
                >
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
                            onChange={(val) => { }}
                        />}
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
                        <TrashIcon
                            className="text-gray-500 cursor-pointer size-4"
                            onClick={() => onRemove(index)}
                        />
                    </div>
                    <div className="flex items-center justify-center">
                        <Switch
                            checked={model.visual || false}
                            onCheckedChange={(checked) => {
                                if (onVisualToggle) {
                                    onVisualToggle(index, checked);
                                }
                            }}
                        />
                    </div>
                </div>
            ))}
            <Button variant="outline" className="border-none size-7 bg-gray-200" size="icon" onClick={onAdd}>
                <Plus className="size-5" />
            </Button>
            {error && <p className="text-red-500 text-xs mt-1">{error}</p>}
        </div>)

    }
)
ModelManagement.displayName = "ModelManagement"