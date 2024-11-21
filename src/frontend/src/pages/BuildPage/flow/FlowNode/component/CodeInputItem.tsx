import { Button } from "@/components/bs-ui/button";
import { Input } from "@/components/bs-ui/input";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";
import { ChevronDown, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import SelectVar from "./SelectVar";

const Item = ({ nodeId, validate, item, index, onUpdateItem, onDeleteItem }) => {
    const handleTypeChange = (newType) => {
        onUpdateItem(index, { ...item, type: newType, label: '', value: '' });
    };

    const handleKeyChange = (e) => {
        onUpdateItem(index, { ...item, key: e.target.value });
    };

    const handleValueChange = (e) => {
        onUpdateItem(index, { ...item, value: e.target.value });
    };

    const [error, setError] = useState(false);

    useEffect(() => {
        if (!validate) return setError(false);
        if (item.key === '' || !/^[a-zA-Z0-9_]{1,50}$/.test(item.key)) {
            setError(true);
        } else {
            setError(false);
        }
    }, [validate])

    return (
        <div className="flex gap-1 items-center mb-1">
            {/* key */}
            <Input value={item.key} onChange={handleKeyChange} className={`${error && 'border-red-500'} h-8`} />
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
            <Trash2 onClick={() => onDeleteItem(index)} className="min-w-5 hover:text-red-600 cursor-pointer" />
        </div>
    );
};


export default function CodeInputItem({ nodeId, data, onValidate, onChange }) {
    const [items, setItems] = useState(data.value);

    const handleAddItem = () => {
        setError(false)
        const newItems = [...items, { key: '', type: 'quote', label: '', value: '' }];
        setItems(newItems);
        onChange(newItems);
    };

    const handleUpdateItem = (index, newItem) => {
        const newItems = items.map((item, i) => (i === index ? newItem : item));
        setItems(newItems);
        onChange(newItems);
    };

    const handleDeleteItem = (index) => {
        const newItems = items.filter((_, i) => i !== index);
        setItems(newItems);
        onChange(newItems);
    };

    const [error, setError] = useState(false)
    useEffect(() => {
        data.required && onValidate(() => {
            setError(false)
            setTimeout(() => {
                setError(true)
            }, 100);

            let msg = ''
            items.some(item => {
                if (item.key === '') {
                    msg = '变量名称不能为空'
                    return true
                } else if (!/^[a-zA-Z0-9_]*$/.test(item.key)) {
                    msg = '变量名称只能包含英文字符、数字和下划线'
                    return true
                } else if (item.key.length > 50) {
                    msg = '变量名称不能超过 50 个字符'
                    return true
                }
            })
            return msg || false
        })

        return () => onValidate(() => { })
    }, [data.value])

    return (
        <div>
            {items.map((item, index) => (
                <Item
                    key={index}
                    validate={error}
                    nodeId={nodeId}
                    item={item}
                    index={index}
                    onUpdateItem={handleUpdateItem}
                    onDeleteItem={handleDeleteItem}
                />
            ))}
            <Button onClick={handleAddItem} variant="outline" className="border-primary text-primary mt-2 h-8">
                +添加新的入参
            </Button>
        </div>
    );
}

