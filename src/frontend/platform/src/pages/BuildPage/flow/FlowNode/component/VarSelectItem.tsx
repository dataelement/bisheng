import { Badge } from "@/components/bs-ui/badge";
import { Label } from "@/components/bs-ui/label";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import { isVarInFlow, updateVariableName } from "@/util/flowUtils";
import { ChevronDown, X } from "lucide-react";
import React, { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import useFlowStore from "../../flowStore";
import { useUpdateVariableState } from "../flowNodeStore";
import SelectVar from "./SelectVar";

export const valueToOutput = (newValues, varZh) => {
    return newValues.map(el => {
        const labelName = varZh[el];
        return {
            key: el.split('.')[1].replace('#', '_'),
            label: labelName.split('/')[1]
        };
    });
};

export default function VarSelectItem({ nodeId, data: paramItem, onChange, onOutPutChange, onValidate, onVarEvent }) {
    const [value, setValue] = React.useState(() => paramItem.value || []);
    const [error, setError] = React.useState(false);

    const updateValue = (newValues) => {
        const outputVar = valueToOutput(newValues, paramItem.varZh || {});
        onOutPutChange(paramItem.linkage, outputVar);
        setValue(newValues);
        onChange(newValues);
    };

    const handleDelete = (val) => updateValue(value.filter(el => el !== val));
    const handleChange = (item, v) => {
        const itemVar = `${item.id}.${v.value}`;
        if (!value.includes(itemVar)) {
            if (!paramItem.varZh) paramItem.varZh = {}; // 确保 paramItem.varZh 已初始化
            paramItem.varZh[itemVar] = `${item.name}/${v.label}`;
            const newValues = [...value, itemVar];
            updateValue(newValues);
        }
    };

    const handleVarChange = useCallback((checked, items) => {
        const newValues = value.filter(el => !items.some(({ node, variable }) => `${node.id}.${variable.value}` === el));
        if (!checked) return updateValue(newValues);

        items.map(({ node, variable }) => {
            const itemVar = `${node.id}.${variable.value}`;
            if (!paramItem.varZh) paramItem.varZh = {};
            paramItem.varZh[itemVar] = `${node.name}/${variable.label}`;
            newValues.push(itemVar);
        })
        updateValue(newValues);
    }, [value]);

    const { t } = useTranslation()
    useEffect(() => {
        paramItem.required && onValidate(() => {
            if (!paramItem.value.length) {
                setError(true)
                return paramItem.label + ' ' + t('required')
            }
            setError(false)
            return false
        })
        return () => onValidate(() => { })
    }, [paramItem.value])


    // 校验变量是否可用
    const { flow } = useFlowStore();
    const [errorKeys, setErrorKeys] = useState<string[]>([])
    const validateVarAvailble = () => {
        let error = ''
        const _errorKeys = []
        value.map(key => {
            const _error = isVarInFlow(nodeId, flow.nodes, key, paramItem.varZh?.[key]);
            if (_error) {
                _errorKeys.push(key)
                error = _error
            }
        })
        setErrorKeys(_errorKeys)
        return Promise.resolve(error);
    };
    useEffect(() => {
        onVarEvent && onVarEvent(validateVarAvailble);
        return () => onVarEvent && onVarEvent(() => { });
    }, [paramItem, value]);

    // Update Preset Questions 
    const [_, forceUpdate] = useState(false)
    const [updateVariable] = useUpdateVariableState()
    useEffect(() => {
        if (!paramItem.varZh) return // No variables, no processing 
        if (!updateVariable) return
        const { action } = updateVariable
        if (action === 'd') {
            // delete paramItem.varZh[key]
            // const newValues = paramItem.value.filter(el => el !== key)
            // setValue(newValues);
            // onChange(newValues);
        } else if (action === 'u') {
            updateVariableName(paramItem, updateVariable)
            forceUpdate(!_)
        }
    }, [updateVariable])

    return <div className='node-item mb-4' data-key={paramItem.key}>
        <div className="flex justify-between items-center">
            <Label className="flex items-center bisheng-label">
                {paramItem.required && <span className="text-red-500">*</span>}
                {paramItem.label}
                {paramItem.help && <QuestionTooltip content={paramItem.help} />}
            </Label>
            <Badge variant="outline" className="bg-[#E6ECF6] text-[#2B53A0]">{paramItem.key}</Badge>
        </div>
        <SelectVar nodeId={nodeId} itemKey={paramItem.key} multip value={value} onSelect={handleChange} onCheck={handleVarChange}>
            <div className={`${error && 'border-red-500'} no-drag nowheel mt-2 group flex min-h-9 w-full items-center justify-between whitespace-nowrap rounded-md border border-input bg-search-input px-3 py-1 text-sm shadow-sm ring-offset-background placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50 [&>span]:line-clamp-1 data-[placeholder]:text-gray-400`}>
                <div className="flex flex-wrap size-full max-h-32 overflow-y-auto">
                    {value.length ? value.map(item => <Badge
                        onPointerDown={(e) => e.stopPropagation()}
                        key={item}
                        className={`flex whitespace-normal items-center gap-1 select-none bg-primary/20 text-primary hover:bg-primary/15 m-[2px] ${errorKeys.includes(item) && 'bg-red-100 border-red-600'}`}>
                        {paramItem.varZh?.[item]}
                        <X className="h-3 w-3 min-w-3" onClick={() => handleDelete(item)}></X>
                    </Badge>
                    ) : <span className="text-gray-400 mt-0.5">{paramItem.placeholder}</span>}
                </div>
                <ChevronDown className="h-5 w-5 min-w-5 opacity-80 group-data-[state=open]:rotate-180" />
            </div>
        </SelectVar>
    </div>
};


// 单选
export function VarSelectSingleItem({ nodeId, data: paramItem, onChange, onValidate, onVarEvent }) {
    const [value, setValue] = React.useState(paramItem.value)
    const { t } = useTranslation()

    const handleChange = (item, v) => {
        // [nodeId.xxx]
        const itemKey = `${item.id}.${v.value}`
        const itemLabel = `${item.name}/${v.label}`
        if (value.key === itemKey) return
        // varZh  {nodeId.xxx: '中文'}
        if (paramItem.varZh) {
            paramItem.varZh[itemKey] = itemLabel
        } else {
            paramItem.varZh = { [itemKey]: itemLabel }
        }
        setValue(itemKey)
        onChange(itemKey)
    }

    const [error, setError] = React.useState(false)
    useEffect(() => {
        paramItem.required && onValidate(() => {
            if (!paramItem.value) {
                setError(true)
                return paramItem.label + t('required')
            }
            setError(false)
            return false
        })
        return () => onValidate(() => { })
    }, [paramItem.value])

    // 校验变量是否可用
    const { flow } = useFlowStore();
    const validateVarAvailble = () => {
        const error = isVarInFlow(nodeId, flow.nodes, value, paramItem.varZh?.[value])
        error && setError(true)
        return Promise.resolve(error);
    };
    useEffect(() => {
        onVarEvent && onVarEvent(validateVarAvailble);
        return () => onVarEvent && onVarEvent(() => { });
    }, [paramItem, value]);

    // Update Preset Questions 
    const [_, forceUpdate] = useState(false)
    const [updateVariable] = useUpdateVariableState()
    useEffect(() => {
        if (!paramItem.varZh) return // No variables, no processing 
        if (!updateVariable) return
        const { action } = updateVariable
        if (action === 'd') {
            // delete paramItem.varZh[key]
            // setValue('')
            // onChange('')
        } else if (action === 'u') {
            updateVariableName(paramItem, updateVariable)
            forceUpdate(!_)
        }
    }, [updateVariable])

    return <div className='node-item mb-4' data-key={paramItem.key}>
        <div className="flex justify-between items-center">
            <Label className="flex items-center bisheng-label">
                {paramItem.required && <span className="text-red-500">*</span>}
                {paramItem.label}
                {paramItem.help && <QuestionTooltip content={paramItem.help} />}
            </Label>
            {/* <Badge variant="outline" className="bg-[#E6ECF6] text-[#2B53A0]">{data.key}</Badge> */}
        </div>
        <SelectVar nodeId={nodeId} itemKey={paramItem.key} onSelect={handleChange}>
            <div className={`${error && 'border-red-500'} no-drag nowheel mt-2 group flex h-9 w-full items-center justify-between whitespace-nowrap rounded-md border border-input bg-search-input px-3 py-1 text-sm shadow-sm ring-offset-background placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50 [&>span]:line-clamp-1 data-[placeholder]:text-gray-400`}>
                <div className="flex flex-wrap">
                    {value ? paramItem.varZh?.[value] : <span className="text-gray-400">{paramItem.placeholder}</span>}
                </div>
                <ChevronDown className="h-5 w-5 min-w-5 opacity-80 group-data-[state=open]:rotate-180" />
            </div>
        </SelectVar>
    </div>
};
