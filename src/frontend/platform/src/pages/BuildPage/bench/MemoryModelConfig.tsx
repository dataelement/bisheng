import { useModel } from "@/pages/ModelPage/manage";
import { ModelSelect } from "@/pages/ModelPage/manage/tabs/KnowledgeModel";
import { useTranslation } from "react-i18next";

interface MemoryModelConfigProps {
    /** Selected model id; empty means the workbench default (first workbench model). */
    value: string;
    onChange: (modelId: string) => void;
}

/** F132: model used to consolidate long-term memory (AC-106). There is deliberately no on/off switch here. */
export function MemoryModelConfig({ value, onChange }: MemoryModelConfigProps) {
    const { t } = useTranslation();
    const { llmOptions } = useModel();

    return (
        <div className="mb-6" data-memory-model>
            <ModelSelect
                close
                label={t("chatConfig.memoryModel")}
                tooltipText={t("chatConfig.memoryModelHint")}
                value={value}
                options={llmOptions}
                placeholder={t("chatConfig.memoryModelPlaceholder")}
                onChange={(modelId: string | null) => onChange(modelId ?? "")}
            />
        </div>
    );
}
