import { Badge } from "@/components/bs-ui/badge";
import { Label } from "@/components/bs-ui/label";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import { isVarInFlow } from "@/util/flowUtils";
import { ChevronDown, X } from "lucide-react";
import { type ComponentType, type ReactNode, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import useFlowStore from "../../flowStore";
import SelectVarUntyped from "./SelectVar";

interface InputFileParam {
    key: string;
    value: string[];
    help?: string;
    placeholder?: string;
    varZh?: Record<string, string>;
}

interface VarNode {
    id: string;
    name: string;
}

interface VarOption {
    value: string;
    label: string;
}

interface SelectVarProps {
    findFilePath?: boolean;
    nodeId: string;
    itemKey: string;
    multip?: boolean;
    value: string[];
    onSelect: (node: VarNode, variable: VarOption) => void;
    onCheck: (checked: boolean, items: { node: VarNode; variable: VarOption }[]) => void;
    children: ReactNode;
}

// SelectVar is an untyped (strict-ignored) component; describe the props used here.
const SelectVar = SelectVarUntyped as unknown as ComponentType<SelectVarProps>;

interface InputFileItemProps {
    nodeId: string;
    data: InputFileParam;
    onChange: (value: string[]) => void;
    onVarEvent: (validate: () => Promise<string>) => void;
    i18nPrefix: string;
}

/**
 * F078: upstream file variables whose originals the agent node copies into its
 * workspace, so a skill can work on the user's own file. Only input-node file
 * path variables are offered.
 */
export function InputFileItem({ nodeId, data, onChange, onVarEvent, i18nPrefix }: InputFileItemProps) {
    const { t } = useTranslation("flow");
    const [value, setValue] = useState<string[]>(() => (Array.isArray(data.value) ? data.value : []));
    const [errorKeys, setErrorKeys] = useState<string[]>([]);
    const { flow } = useFlowStore();

    const updateValue = (next: string[]) => {
        setValue(next);
        onChange(next);
    };

    const remember = (node: VarNode, variable: VarOption) => {
        const key = `${node.id}.${variable.value}`;
        if (!data.varZh) data.varZh = {};
        data.varZh[key] = `${node.name}/${variable.label}`;
        return key;
    };

    const handleSelect = (node: VarNode, variable: VarOption) => {
        const key = remember(node, variable);
        if (!value.includes(key)) updateValue([...value, key]);
    };

    const handleCheck = (checked: boolean, items: { node: VarNode; variable: VarOption }[]) => {
        const keys = items.map(({ node, variable }) => `${node.id}.${variable.value}`);
        const rest = value.filter((one) => !keys.includes(one));
        if (!checked) return updateValue(rest);
        updateValue([...rest, ...items.map(({ node, variable }) => remember(node, variable))]);
    };

    // The node keeps validators in refs, so registering again on every change is cheap;
    // the ref lets the registered function always see the latest selection.
    const validateRef = useRef<() => Promise<string>>(() => Promise.resolve(""));
    validateRef.current = () => {
        let error = "";
        const broken: string[] = [];
        value.forEach((key) => {
            const message = isVarInFlow(nodeId, flow.nodes, key, data.varZh?.[key]);
            if (message) {
                broken.push(key);
                error = message;
            }
        });
        setErrorKeys(broken);
        return Promise.resolve(error);
    };
    useEffect(() => {
        if (!onVarEvent) return;
        onVarEvent(() => validateRef.current());
        return () => onVarEvent(() => Promise.resolve(""));
    }, [onVarEvent]);

    return (
        <div className="node-item mb-4" data-key={data.key}>
            <Label className="flex items-center bisheng-label mb-2">
                {t(`${i18nPrefix}label`)}
                {data.help && <QuestionTooltip content={t(`${i18nPrefix}help`)} />}
            </Label>
            <SelectVar
                findFilePath
                nodeId={nodeId}
                itemKey={data.key}
                multip
                value={value}
                onSelect={handleSelect}
                onCheck={handleCheck}
            >
                <div className="no-drag nowheel group flex min-h-9 w-full items-center justify-between whitespace-nowrap rounded-md border border-input bg-search-input px-3 py-1 text-sm shadow-sm">
                    <div className="flex flex-wrap size-full max-h-32 overflow-y-auto">
                        {value.length ? (
                            value.map((key) => (
                                <Badge
                                    onPointerDown={(e) => e.stopPropagation()}
                                    key={key}
                                    className={`flex whitespace-normal items-center gap-1 select-none bg-primary/20 text-primary hover:bg-primary/15 m-[2px] ${errorKeys.includes(key) && "bg-red-100 border-red-600"}`}
                                >
                                    {data.varZh?.[key] || key}
                                    <X className="h-3 w-3 min-w-3" onClick={() => updateValue(value.filter((one) => one !== key))} />
                                </Badge>
                            ))
                        ) : (
                            <span className="text-gray-400 mt-0.5">{t(`${i18nPrefix}placeholder`)}</span>
                        )}
                    </div>
                    <ChevronDown className="h-5 w-5 min-w-5 opacity-80 group-data-[state=open]:rotate-180" />
                </div>
            </SelectVar>
        </div>
    );
}
