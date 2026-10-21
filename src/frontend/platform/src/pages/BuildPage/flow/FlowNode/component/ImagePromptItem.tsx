// @ts-strict-ignore
import { Label } from "@/components/bs-ui/label";
import { AppHint as QuestionTooltip } from "@/pages/BuildPage/components/AppHint";
import { isVarInFlow } from "@/util/flowUtils";
import { Switch,Tag } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";

import React,{ useCallback,useEffect,useState } from "react";
import { useTranslation } from "react-i18next";
import useFlowStore from "../../flowStore";
import SelectVar from "./SelectVar";

export default function ImagePromptItem({ nodeId, data, onChange, onVarEvent, i18nPrefix }) {
    // value ''或[] 则认为open为false
    const [open, setOpen] = React.useState(data.open || false)
    const [value, setValue] = React.useState(() => data.value || []);
    const [error] = React.useState(false);
    const { t } = useTranslation('flow')

    const updateValue = (newValues) => {
        setValue(newValues);
        onChange(newValues);
    };

    const handleDelete = (val) => updateValue(value.filter(el => el !== val));
    const handleChange = (item, v) => {
        const itemVar = `${item.id}.${v.value}`;
        if (!value.includes(itemVar)) {
            if (!data.varZh) data.varZh = {}; // 确保 data.varZh 已初始化
            data.varZh[itemVar] = `${item.name}/${v.label}`;
            const newValues = [...value, itemVar];
            updateValue(newValues);
        }
    };

    const handleVarChange = useCallback((checked, items) => {
        const newValues = value.filter(el => !items.some(({ node, variable }) => `${node.id}.${variable.value}` === el));
        if (!checked) return updateValue(newValues);

        items.map(({ node, variable }) => {
            const itemVar = `${node.id}.${variable.value}`;
            if (!data.varZh) data.varZh = {};
            data.varZh[itemVar] = `${node.name}/${variable.label}`;
            newValues.push(itemVar);
        })
        updateValue(newValues);
    }, [value]);

    // 校验变量是否可用
    const { flow } = useFlowStore();
    const [errorKeys, setErrorKeys] = useState<string[]>([])
    const validateVarAvailble = () => {
        let error = ''
        const _errorKeys = []
        value.map(key => {
            const _error = isVarInFlow(nodeId, flow.nodes, key, data.varZh?.[key]);
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
    }, [data, value]);


    return <div className='node-item mb-4' data-key={data.key}>
        <div className=" flex justify-between items-center">
            <Label className="flex items-center bisheng-label">
                {t(`${i18nPrefix}label`)}
                {data.help && <QuestionTooltip content={t(`${i18nPrefix}help`)} />}
            </Label>
            <Switch checked={open} onCheckedChange={(bln) => {
                setOpen(bln)
                data.open = bln
                !bln && updateValue([])
            }} />
        </div>
        {open && <SelectVar
            findInputFile
            nodeId={nodeId}
            itemKey={data.key}
            multip
            value={value}
            onSelect={handleChange}
            onCheck={handleVarChange}
        >
            <div className={`${error && 'border-red-500'} no-drag nowheel mt-2 group flex min-h-9 w-full items-center justify-between whitespace-nowrap rounded-md border border-input bg-search-input px-3 py-1 text-sm shadow-sm ring-offset-background placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50 [&>span]:line-clamp-1 data-[placeholder]:text-gray-400`}>
                <div className="flex flex-wrap size-full max-h-32 overflow-y-auto">
                    {value.length ? value.map(item => <span key={item} className="inline-flex max-w-full" onPointerDown={(e) => e.stopPropagation()}>
                        <Tag size="small" color={errorKeys.includes(item) ? "danger" : "brand"} className="m-[2px] select-none whitespace-nowrap">
                            <span className="inline-flex items-center gap-1 whitespace-nowrap">
                                {data.varZh?.[item]}
                                <Outlined.Close className="h-3 w-3 shrink-0" onClick={(e) => { e.stopPropagation(); handleDelete(item); }} />
                            </span>
                        </Tag>
                    </span>
                    ) : <span className="text-gray-400 mt-0.5">{data.placeholder && t(`${i18nPrefix}placeholder`)}</span>}
                </div>
                <Outlined.Down className="h-5 w-5 min-w-5 opacity-80 group-data-[state=open]:rotate-180" />
            </div>
        </SelectVar>
        }
    </div>
};
