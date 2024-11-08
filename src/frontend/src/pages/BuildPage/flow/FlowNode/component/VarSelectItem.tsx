import { Badge } from "@/components/bs-ui/badge";
import { Label } from "@/components/bs-ui/label";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import { ChevronDown, X } from "lucide-react";
import React from "react";
import SelectVar from "./SelectVar";

export default function VarSelectItem({ nodeId, data, onChange, onOutPutChange }) {
    const [value, setValue] = React.useState(data.value)

    const handleDelete = (val) => {
        const newValues = value.filter(el => el !== val)
        const outputVar = valueToOutput(newValues)

        onOutPutChange(data.linkage, outputVar)
        setValue(newValues)
        onChange(newValues)
    }

    const handleChange = (item, v) => {
        // [nodeId.xxx]
        const itemVar = `${item.id}.${v.value}`
        if (value.includes(itemVar)) return
        const newValues = [...value, itemVar]
        // varZh  {nodeId.xxx: '中文'}
        if (data.varZh) {
            data.varZh[itemVar] = `${item.name}/${v.label}`
        } else {
            data.varZh = { [itemVar]: `${item.name}/${v.label}` }
        }
        // output {key: xxx , label: '中文'}[]
        const outputVar = valueToOutput(newValues)

        onOutPutChange(data.linkage, outputVar)
        setValue(newValues)
        onChange(newValues)
    }

    const valueToOutput = (newValues) => {
        return newValues.map(el => {
            const labelName = data.varZh[el]
            return {
                key: el,
                label: labelName.split('/')[1]
            }
        })
    }

    return <div className='node-item mb-4' data-key={data.key}>
        <div className="flex justify-between items-center">
            <Label className="flex items-center bisheng-label">
                {data.required && <span className="text-red-500">*</span>}
                {data.label}
                {data.help && <QuestionTooltip content={data.help} />}
            </Label>
            <Badge variant="outline" className="bg-[#E6ECF6] text-[#2B53A0]">{data.key}</Badge>
        </div>
        <SelectVar nodeId={nodeId} itemKey={data.key} onSelect={handleChange}>
            <div className="no-drag nowheel mt-2 group flex h-9 w-full items-center justify-between whitespace-nowrap rounded-md border border-input bg-search-input px-3 py-1 text-sm shadow-sm ring-offset-background placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50 [&>span]:line-clamp-1 data-[placeholder]:text-gray-400">
                <div className="flex flex-wrap size-full overflow-y-auto">
                    {value.map(item => <Badge onPointerDown={(e) => e.stopPropagation()} key={item} className="flex whitespace-normal items-center gap-1 select-none bg-primary/20 text-primary hover:bg-primary/15 m-[2px]">
                        {data.varZh[item]}
                        <X className="h-3 w-3" onClick={() => handleDelete(item)}></X>
                    </Badge>
                    )}
                </div>
                <ChevronDown className="h-5 w-5 min-w-5 opacity-80 group-data-[state=open]:rotate-180" />
            </div>
        </SelectVar>
    </div>
};


// 单选
export function VarSelectSingleItem({ nodeId, data, onChange }) {
    const [value, setValue] = React.useState(data.value)

    const handleChange = (item, v) => {
        // [nodeId.xxx]
        const itemKey = `${item.id}.${v.value}`
        const itemLabel = `${item.name}/${v.label}`
        if (value.key === itemKey) return
        // varZh  {nodeId.xxx: '中文'}
        if (data.varZh) {
            data.varZh[itemKey] = itemLabel
        } else {
            data.varZh = { [itemKey]: itemLabel }
        }
        setValue(itemKey)
        onChange(itemKey)
    }


    return <div className='node-item mb-4' data-key={data.key}>
        <div className="flex justify-between items-center">
            <Label className="flex items-center bisheng-label">
                {data.required && <span className="text-red-500">*</span>}
                {data.label}
                {data.help && <QuestionTooltip content={data.help} />}
            </Label>
            {/* <Badge variant="outline" className="bg-[#E6ECF6] text-[#2B53A0]">{data.key}</Badge> */}
        </div>
        <SelectVar nodeId={nodeId} itemKey={data.key} onSelect={handleChange}>
            <div className="no-drag nowheel mt-2 group flex h-9 w-full items-center justify-between whitespace-nowrap rounded-md border border-input bg-search-input px-3 py-1 text-sm shadow-sm ring-offset-background placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50 [&>span]:line-clamp-1 data-[placeholder]:text-gray-400">
                <div className="flex flex-wrap">
                    {data.varZh?.[value] || ''}
                </div>
                <ChevronDown className="h-5 w-5 min-w-5 opacity-80 group-data-[state=open]:rotate-180" />
            </div>
        </SelectVar>
    </div>
};
