import { Badge } from "@/components/bs-ui/badge";
import { Label } from "@/components/bs-ui/label";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import { ChevronDown, X } from "lucide-react";
import React from "react";
import SelectVar from "./SelectVar";

export default function VarSelectItem({ nodeId, data, onChange, onOutPutChange }) {
    const [value, setValue] = React.useState(data.value)

    const handleDelete = (key) => {
        const newValue = value.filter(el => el.key !== key)
        onOutPutChange(data.linkage, newValue)
        setValue(newValue)
        onChange(newValue)
    }

    const handleChange = (item, v) => {
        console.log('item, v :>> ', item, v);
        if (value.some(el => el.key === v.value)) return
        const newValue = [...value, {
            key: v.value,
            label: v.label
        }]
        onOutPutChange(data.linkage, newValue)
        setValue(newValue)
        onChange(newValue)
    }

    return <div className='node-item mb-2' data-key={data.key}>
        <div className="flex justify-between items-center">
            <Label className="flex items-center bisheng-label">
                {data.required && <span className="text-red-500">*</span>}
                {data.label}
                {data.help && <QuestionTooltip content={data.help} />}
            </Label>
            <Badge variant="outline" className="bg-input text-muted-foreground">{data.key}</Badge>
        </div>
        <SelectVar nodeId={nodeId} onSelect={handleChange}>
            <div className="no-drag nowheel mt-2 group flex h-9 w-full items-center justify-between whitespace-nowrap rounded-md border border-input bg-search-input px-3 py-1 text-sm shadow-sm ring-offset-background placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50 [&>span]:line-clamp-1 data-[placeholder]:text-gray-400">
                <div className="flex flex-wrap size-full overflow-y-auto">
                    {value.map(item => <Badge onPointerDown={(e) => e.stopPropagation()} key={item.key} className="flex whitespace-normal items-center gap-1 select-none bg-primary/20 text-primary hover:bg-primary/15 m-[2px]">
                        {item.label}
                        <X className="h-3 w-3" onClick={() => handleDelete(item.key)}></X>
                    </Badge>
                    )}
                </div>
                <ChevronDown className="h-5 w-5 min-w-5 opacity-80 group-data-[state=open]:rotate-180" />
            </div>
        </SelectVar>
    </div>
};
