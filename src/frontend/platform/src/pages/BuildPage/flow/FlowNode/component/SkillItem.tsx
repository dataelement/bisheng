import { Label } from "@/components/bs-ui/label";
import MultiSelect from "@/components/bs-ui/select/multi";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import { getAssistantModelConfig } from "@/controllers/API/finetune";
import { skillApi } from "@/controllers/API/linsight";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

interface SkillOption {
    key: string;
    label: string;
}

interface SkillParam {
    key: string;
    value: SkillOption[];
    help?: string;
}

interface FlowNodeParam {
    key: string;
    value: unknown;
}

interface FlowNodeData {
    group_params: { params: FlowNodeParam[] }[];
}

interface SkillItemProps {
    node: FlowNodeData;
    data: SkillParam;
    onChange: (value: SkillOption[]) => void;
    i18nPrefix: string;
}

interface AssistantModel {
    model_id: string | number;
    agent_executor_type?: string;
}

const REACT_EXECUTOR = "ReAct";

const findModelId = (node: FlowNodeData) => {
    for (const group of node.group_params) {
        const param = group.params.find((one) => one.key === "model_id");
        if (param) return param.value;
    }
    return undefined;
};

/**
 * F078: pick the skills an agent node may use. Only function-call models can run
 * skills, so the picker is disabled for a ReAct model. The backend checks again
 * at run time, because the node configuration comes from the client.
 */
export function SkillItem({ node, data, onChange, i18nPrefix }: SkillItemProps) {
    const { t } = useTranslation("flow");
    const [selected, setSelected] = useState<SkillOption[]>(() => data.value || []);
    const [available, setAvailable] = useState<SkillOption[]>([]);
    const [models, setModels] = useState<AssistantModel[]>([]);

    useEffect(() => {
        getAssistantModelConfig()
            .then((res: { llm_list?: AssistantModel[] }) => setModels(res?.llm_list || []))
            .catch(() => setModels([]));
    }, []);

    const loadSkills = () => {
        captureAndAlertRequestErrorHoc(skillApi.getSelectableSkills()).then((res) => {
            if (!Array.isArray(res)) return;
            // Drop rows without a name: an empty value breaks the select.
            setAvailable(res.filter((one) => one.name).map((one) => ({ key: one.name, label: one.display_name || one.name })));
        });
    };

    const modelId = findModelId(node);
    const isReact = models.some(
        (one) => String(one.model_id) === String(modelId) && one.agent_executor_type === REACT_EXECUTOR
    );

    // Keep already-selected skills as options so their labels show before the list loads.
    const options = useMemo(() => {
        const merged = new Map<string, string>();
        selected.forEach((one) => merged.set(one.key, one.label));
        available.forEach((one) => merged.set(one.key, one.label));
        return Array.from(merged, ([value, label]) => ({ value, label }));
    }, [selected, available]);

    const handleChange = (keys: string[]) => {
        const labels = new Map(options.map((one) => [one.value, one.label]));
        const next = keys.map((key) => ({ key, label: labels.get(key) || key }));
        setSelected(next);
        onChange(next);
    };

    return (
        <div className="node-item mb-4" data-key={data.key}>
            <Label className="flex items-center bisheng-label mb-2">
                {t(`${i18nPrefix}label`)}
                {data.help && <QuestionTooltip content={t(`${i18nPrefix}help`)} />}
            </Label>
            <MultiSelect
                id={`skill-select-${data.key}`}
                multiple
                disabled={isReact}
                value={selected.map((one) => one.key)}
                options={options}
                placeholder={t(`${i18nPrefix}placeholder`)}
                searchPlaceholder={t(`${i18nPrefix}search`)}
                onChange={handleChange}
                onLoad={loadSkills}
            />
            {isReact && <p className="mt-1 text-xs text-muted-foreground">{t(`${i18nPrefix}react_disabled`)}</p>}
        </div>
    );
}
