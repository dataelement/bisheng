import { Badge } from "@/components/bs-ui/badge"
import { Label } from "@/components/bs-ui/label"
import { Switch } from "@/components/bs-ui/switch"
import { QuestionTooltip } from "@/components/bs-ui/tooltip"
import { isVarInFlow } from "@/util/flowUtils"
import { ChevronDown, X } from "lucide-react"
import React, { useCallback, useEffect, useState } from "react"
import useFlowStore from "../../flowStore"
import SelectVar from "./SelectVar"

export default function ImagePromptItem({ nodeId, data, onChange, onVarEvent }) {
    // value ''或[] 则认为open为false
    const [open, setOpen] = React.useState(data.open || false)
    const [value, setValue] = React.useState(() => data.value || []);
    const [error, setError] = React.useState(false);

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
                {data.label}
                {data.help && <QuestionTooltip content={data.help} />}
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
                    {value.length ? value.map(item => <Badge
                        onPointerDown={(e) => e.stopPropagation()}
                        key={item}
                        className={`flex whitespace-normal items-center gap-1 select-none bg-primary/20 text-primary hover:bg-primary/15 m-[2px] ${errorKeys.includes(item) && 'bg-red-100 border-red-600'}`}>
                        {data.varZh?.[item]}
                        <X className="h-3 w-3 min-w-3" onClick={() => handleDelete(item)}></X>
                    </Badge>
                    ) : <span className="text-gray-400 mt-0.5">{data.placeholder}</span>}
                </div>
                <ChevronDown className="h-5 w-5 min-w-5 opacity-80 group-data-[state=open]:rotate-180" />
            </div>
        </SelectVar>
        }
    </div>
};
