import { Input } from "@/components/bs-ui/input";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";
import SelectVar from "./SelectVar";
import { ChevronDown, Trash2 } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/bs-ui/button";
import { generateUUID } from "@/components/bs-ui/utils";

const Item = ({ nodeId, item, index, onUpdateItem, onDeleteItem }) => {
    const handleTypeChange = (newType) => {
        onUpdateItem(index, { ...item, type: newType, label: '', value: '' });
    };

    const handleKeyChange = (e) => {
        onUpdateItem(index, { ...item, key: e.target.value });
    };

    const handleValueChange = (e) => {
        onUpdateItem(index, { ...item, value: e.target.value });
    };

    return (
        <div className="flex gap-1 items-center mb-1">
            {/* key */}
            <SelectVar nodeId={nodeId} itemKey={''} onSelect={(E, v) => {
                onUpdateItem(index, { ...item, label: v.label, value: `${E.id}.${v.value}` })
            }}>
                <div className="no-drag nowheel group flex h-8 w-full items-center justify-between whitespace-nowrap rounded-md border border-input bg-search-input px-3 py-1 text-sm shadow-sm ring-offset-background placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50 [&>span]:line-clamp-1 data-[placeholder]:text-gray-400">
                    <span className="flex items-center">
                        {item.label}
                    </span>
                    <ChevronDown className="h-5 w-5 min-w-5 opacity-80 group-data-[state=open]:rotate-180" />
                </div>
            </SelectVar>
            <Select value={item.type} onValueChange={handleTypeChange}>
                <SelectTrigger className="max-w-32 w-24 h-8">
                    <SelectValue placeholder="选择条件" />
                </SelectTrigger>
                <SelectContent>
                    <SelectGroup>
                        <SelectItem value="quote">引用</SelectItem>
                        <SelectItem value="input">输入</SelectItem>
                    </SelectGroup>
                </SelectContent>
            </Select>
            {/* type */}
            <Select value={item.type} onValueChange={handleTypeChange}>
                <SelectTrigger className="max-w-32 w-24 h-8">
                    <SelectValue placeholder="类型" />
                </SelectTrigger>
                <SelectContent>
                    <SelectGroup>
                        <SelectItem value="quote">引用</SelectItem>
                        <SelectItem value="input">输入</SelectItem>
                    </SelectGroup>
                </SelectContent>
            </Select>
            {/* value */}
            {item.type === 'quote' ? <SelectVar nodeId={nodeId} itemKey={''} onSelect={(E, v) => {
                onUpdateItem(index, { ...item, label: v.label, value: `${E.id}.${v.value}` })
            }}>
                <div className="no-drag nowheel group flex h-8 w-full items-center justify-between whitespace-nowrap rounded-md border border-input bg-search-input px-3 py-1 text-sm shadow-sm ring-offset-background placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50 [&>span]:line-clamp-1 data-[placeholder]:text-gray-400">
                    <span className="flex items-center">
                        {item.label}
                    </span>
                    <ChevronDown className="h-5 w-5 min-w-5 opacity-80 group-data-[state=open]:rotate-180" />
                </div>
            </SelectVar> : <Input value={item.value} onChange={handleValueChange} className="h-8" />}
            <Trash2 size={18} onClick={() => onDeleteItem(index)} className="min-w-5 hover:text-red-600 cursor-pointer" />
        </div>
    );
};

export default function ConditionItem({ nodeId, data, onChange }) {
    const [value, setValue] = useState([] || data.value);
    // {
    //     "id": "",
    //     "operator": "and/...",
    //     "conditions":
    //     {
    //         "id": "",
    //         "left_var": "",
    //         "comparison_operation": "",
    //         "right_value_type": "", // ref 表示引用
    //         "right_value": ""
    //     }
    // }

    const handleAddCondition = () => {
        setValue((val) => [...val, { id: generateUUID(8), operator: 'and', conditions: [] }]);
    }

    const deleteCondition = (id) => {
        setValue((val) => val.filter(item => item.id !== id));
    }

    const handleAddItem = (id) => {
        setValue((val) => val.map(item => {
            if (item.id === id) {
                item.conditions.push({
                    id: generateUUID(8),
                    left_var: '',
                    comparison_operation: '',
                    right_value_type: '',
                    right_value: ''
                })
            }
            return item;
        }))
    }

    return <div>
        {
            value.map(val => <div>
                <div className="flex justify-between items-center">
                    <p className='mt-2 mb-3 text-sm font-bold'>如果</p>
                    <Trash2 size={14} onClick={() => deleteCondition(val.id)} className="hover:text-red-600 cursor-pointer" />
                </div>
                <div>
                    {val.conditions.map((item, index) =>
                        <Item
                            key={item.id}
                            nodeId={nodeId}
                            item={item}
                            index={index}
                            onUpdateItem={(index, item) => {
                                // val.conditions[index] = item;
                                // setValue([...value]);
                                // onChange(value);
                            }}
                            onDeleteItem={() => { }}
                        />)}
                </div>
                <Button onClick={() => handleAddItem(val.id)} variant="outline" className="border-primary text-primary mt-2 h-8">
                    + 添加条件
                </Button>
            </div>)
        }

        <div>
            <p className='mt-2 mb-3 text-sm font-bold'>否则</p>
            <div>

            </div>
        </div>
        <Button onClick={handleAddCondition} variant="outline" className="border-primary text-primary mt-2 h-8">
            + 添加分支
        </Button>
    </div>
};
