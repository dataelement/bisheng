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
import { useNavigate } from "react-router-dom";

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
    /** Linsight default model: the model id used as the default executor for Linsight tasks. */
    linsightDefaultModelId?: string | null;
    onLinsightDefaultChange?: (id: string) => void;
}
export const ModelManagement = forwardRef<HTMLDivElement[], ModelManagementProps>(
    ({ models, errors, error, onAdd, onRemove, onModelChange, onNameChange, onVisualToggle, linsightDefaultModelId, onLinsightDefaultChange }, ref) => {
        // `assistant` mode hits /api/v1/llm/assistant/llm_list which is already
        // filtered to the admin-configured assistant allowlist (default model
        // and its server are placed first). Avoids the fetch-all + client-side
        // filter round-trip.
        const { llmOptions: assistantLlmOptions } = useModel('assistant');
        const { t } = useTranslation();
        const navigate = useNavigate();

        const selectFooter = (
            <div
                className="px-3 py-2 text-sm text-primary cursor-pointer hover:bg-[#EBF0FF] dark:hover:bg-gray-700"
                onMouseDown={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    navigate('/model/management?systemModel=assis');
                }}
            >
                + {t('bench.addMoreModels')}
            </div>
        );

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
            <div className="mt-2 border p-4 rounded-md bg-background">
                <div className="grid mb-4 items-center" style={{ gridTemplateColumns: "1.35fr 1fr 72px 116px 36px" }}>
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
                    <div className="flex items-center justify-center">
                        <Label className="bisheng-label whitespace-nowrap mr-0.5">{t('model:model.linsightDefaultModel')}</Label>
                        <QuestionTooltip className="text-[#999999]" content={t('model:model.linsightDefaultModelTooltip')} />
                    </div>
                    <div className="text-center">
                    </div>
                </div>

                {models.map((model, index) => (
                    <div
                        key={model.key}
                        ref={(el) => setItemRef(el, index)}
                        className="grid items-center mb-4"
                        style={{ gridTemplateColumns: "1.35fr 1fr 72px 116px 36px" }}
                    >
                        <div className="pr-2" id={model.id}>
                            {assistantLlmOptions.length > 0 ? (
                                <ModelSelect
                                    key={model.id}
                                    label={''}
                                    value={model.id}
                                    options={assistantLlmOptions}
                                    onChange={(val) => onModelChange(index, val)}
                                    footer={selectFooter}
                                />
                            ) : (
                                <ModelSelect
                                    key={'model.id'}
                                    label={''}
                                    value={''}
                                    options={[]}
                                    onChange={(val) => { }}
                                    footer={selectFooter}
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

                        {/* Linsight default model: single-select radio across the whole column */}
                        <div className="flex items-center justify-center">
                            <input
                                type="radio"
                                name="linsight-default-model"
                                className="size-4 cursor-pointer accent-primary disabled:cursor-not-allowed"
                                checked={!!model.id && model.id === linsightDefaultModelId}
                                disabled={!model.id}
                                onChange={() => model.id && onLinsightDefaultChange?.(model.id)}
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
