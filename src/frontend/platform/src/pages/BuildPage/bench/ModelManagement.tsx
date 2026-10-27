// @ts-strict-ignore
import { Button, Input } from '@bisheng/ui';
import { Checkbox, Tooltip } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
// src/features/chat-config/components/ModelManagement.tsx

import { QuestionHint as QuestionTooltip } from "@/components/bs-comp/QuestionHint";


import { Label } from "@/components/bs-ui/label";
import { useModel } from "@/pages/ModelPage/manage";
import { ModelSelect } from "@/pages/ModelPage/manage/tabs/KnowledgeModel";

import { forwardRef } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

// Keep in sync with backend WSModel (bisheng/api/v1/schemas.py).
export const MODEL_DESCRIPTION_MAX_LENGTH = 50;

export interface Model {
    key: string;
    id: string;
    name: string;
    displayName: string;
    /** Optional one-line intro shown in the workspace model picker. */
    description?: string;
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
    onDescriptionChange?: (index: number, description: string) => void;
    onVisualToggle?: (index: number, enabled: boolean) => void;
    /** Daily-mode default model: used for new daily conversations when the user has no valid manual selection. */
    chatDefaultModelId?: string | null;
    onChatDefaultChange?: (id: string) => void;
    /** Linsight default model: the model id used as the default executor for Linsight tasks. */
    linsightDefaultModelId?: string | null;
    onLinsightDefaultChange?: (id: string) => void;
}

/** One source of truth for the header row and every model row — they have to
 *  line up, and the two used to carry the same literal twice, so widening one
 *  silently broke the alignment. The three trailing columns are wider than the
 *  Chinese text needs because English and Japanese labels are longer. */
const MODEL_ROW_COLUMNS =
    "minmax(220px, 1.2fr) minmax(160px, 0.9fr) minmax(240px, 1.3fr) 88px 140px 140px 36px";

export const ModelManagement = forwardRef<HTMLDivElement[], ModelManagementProps>(
    (
        {
            models,
            errors,
            error,
            onAdd,
            onRemove,
            onModelChange,
            onNameChange,
            onDescriptionChange,
            onVisualToggle,
            chatDefaultModelId,
            onChatDefaultChange,
            linsightDefaultModelId,
            onLinsightDefaultChange,
        },
        ref,
    ) => {
        // `assistant` mode hits /api/v1/llm/assistant/llm_list which is already
        // filtered to the admin-configured assistant allowlist (default model
        // and its server are placed first). Avoids the fetch-all + client-side
        // filter round-trip.
        const { llmOptions: assistantLlmOptions } = useModel("assistant");
        const { t } = useTranslation();
        const navigate = useNavigate();

        // Resolve the selected model's name from the provider-grouped options so the
        // display-name input can fall back to it as placeholder when left empty.
        const getModelLabel = (id: string) => {
            if (!id) return "";
            for (const group of assistantLlmOptions) {
                const hit = group.children?.find((el) => el.value == id);
                if (hit) return hit.label;
            }
            return "";
        };

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
            <div className="mt-2 border p-4 rounded-md bg-background overflow-x-auto">
                <div className="min-w-[1072px]">
                    <div className="grid mb-4 items-end gap-x-2" style={{ gridTemplateColumns: MODEL_ROW_COLUMNS }}>
                        <div className="min-w-0">
                            <Label className="bisheng-label">{t("bench.model")}</Label>
                        </div>
                        <div className="min-w-0">
                            <Label className="bisheng-label">{t("bench.displayName")}</Label>
                        </div>
                        <div className="min-w-0">
                            <Label className="bisheng-label">{t("bench.modelDescription")}</Label>
                        </div>
                        {/* No whitespace-nowrap on these three: the cells are fixed-width
                        while the labels are translated, so nowrap made English and
                        Japanese overflow and paint on top of the next column
                        ("Vision" over "Linsight Default Model"). Wrapping keeps a long
                        translation inside its own column whatever its length. */}
                        <div className="flex items-center justify-center gap-0.5 px-1 text-center">
                            <Label className="bisheng-label">{t("bench.vision")}</Label>
                            <QuestionTooltip className="shrink-0" content={t("bench.visionText")} />
                        </div>
                        <div className="flex items-center justify-center px-1 text-center">
                            <Label className="bisheng-label">{t("model:model.dailyDefaultModel")}</Label>
                        </div>
                        <div className="flex items-center justify-center gap-0.5 px-1 text-center">
                            <Label className="bisheng-label">{t("model:model.linsightDefaultModel")}</Label>
                            <QuestionTooltip
                                className="shrink-0"
                                content={t("model:model.linsightDefaultModelTooltip")}
                            />
                        </div>
                        <div className="text-center"></div>
                    </div>

                    {models.map((model, index) => (
                        <div
                            key={model.key}
                            ref={(el) => setItemRef(el, index)}
                            className="grid items-center mb-4 gap-x-2"
                            style={{ gridTemplateColumns: MODEL_ROW_COLUMNS }}
                        >
                            <div className="min-w-0" id={model.id}>
                                {assistantLlmOptions.length > 0 ? (
                                    <ModelSelect
                                        key={model.id}
                                        label={""}
                                        value={model.id}
                                        options={assistantLlmOptions}
                                        onChange={(val) => onModelChange(index, val)}
                                    />
                                ) : (
                                    <ModelSelect
                                        key={"model.id"}
                                        label={""}
                                        value={""}
                                        options={[]}
                                        onChange={(val) => {}}
                                    />
                                )}
                                {errors[model.key] && (
                                    <p className="text-red-500 text-xs mt-1">{errors[model.key]?.[0]}</p>
                                )}
                            </div>
                            <div className="min-w-0">
                                <Input value={model.displayName} onChange={(e) => onNameChange(index, e.target.value)} placeholder={getModelLabel(model.id) || t("bench.displayName")} />
                                {errors[model.key] && (
                                    <p className="text-red-500 text-xs mt-1">{errors[model.key]?.[1]}</p>
                                )}
                            </div>
                            <div className="min-w-0">
                                <Input value={model.description || ""} maxLength={MODEL_DESCRIPTION_MAX_LENGTH} onChange={(e) => onDescriptionChange?.(index, e.target.value)} placeholder={t("bench.modelDescriptionPlaceholder")} showCount />
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

                            {/* Daily-mode default model: single-select radio across the whole column */}
                            <div className="flex items-center justify-center">
                                <input
                                    type="radio"
                                    name="chat-default-model"
                                    className="size-4 cursor-pointer accent-primary disabled:cursor-not-allowed"
                                    checked={!!model.id && String(model.id) === String(chatDefaultModelId ?? "")}
                                    disabled={!model.id}
                                    onChange={() => model.id && onChatDefaultChange?.(model.id)}
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

                            {}
                            <div className="flex items-center justify-center">
                                <Tooltip content={t("delete")}>
                                    <Button type="button" variant="text" size="small" iconOnly aria-label={t("delete")} onClick={() => onRemove(index)}>
                                        <Outlined.Delete className="text-gray-500 cursor-pointer size-4 hover:text-red-500 transition-colors" />
                                    </Button>
                                </Tooltip>
                            </div>
                        </div>
                    ))}
                </div>
                <div className="mt-2 flex items-center gap-3">
                    <Button variant="outlined" size="small" iconOnly onClick={onAdd} color="default">
                        <Outlined.Plus className="size-5" />
                    </Button>
                    {/* Lived in the dropdown footer of the old cascader; the shared Select has no footer slot. */}
                    <Button variant="link" size="small" onClick={() => navigate("/model/management?systemModel=assis")}>
                        {t("bench.addMoreModels")}
                    </Button>
                </div>

                {error && <p className="text-red-500 text-xs mt-1">{error}</p>}
            </div>
        );
    },
);
ModelManagement.displayName = "ModelManagement";
