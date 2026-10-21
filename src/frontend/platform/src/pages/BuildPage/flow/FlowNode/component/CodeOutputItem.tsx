// @ts-strict-ignore
import { Button, Input } from '@bisheng/ui';


import { Select,SelectContent,SelectGroup,SelectItem,SelectTrigger,SelectValue } from "@/components/bs-ui/select";
import { Outlined } from "bisheng-icons";

import { useEffect,useState } from "react";
import { useTranslation } from 'react-i18next';

const Item = ({ item, index, validate, onUpdateItem, onDeleteItem }) => {
    const { t } = useTranslation('flow');

    const handleTypeChange = (newType) => {
        onUpdateItem(index, { ...item, type: newType });
    };

    const handleKeyChange = (e) => {
        onUpdateItem(index, { ...item, key: e.target.value });
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
            <Input value={item.key} placeholder={t('parameterName')} onChange={handleKeyChange} className={`${error && 'border-red-500'} h-8`} />
            {/* type */}
            <Select value={item.type} onValueChange={handleTypeChange}>
                <SelectTrigger className="max-w-32 w-24 h-8">
                    <SelectValue placeholder={t('dataType')} />
                </SelectTrigger>
                <SelectContent>
                    <SelectGroup>
                        <SelectItem value="str">String</SelectItem>
                        <SelectItem value="list">List</SelectItem>
                    </SelectGroup>
                </SelectContent>
            </Select>
            <Outlined.Delete size={16} onClick={() => onDeleteItem(index)} className="min-w-5 hover:text-red-600 cursor-pointer" />
        </div>
    );
};

export default function CodeOutputItem({ nodeId, data, onValidate, onChange, i18nPrefix }) {
    const { t } = useTranslation('flow');
    const [items, setItems] = useState(data.value);

    const handleAddItem = () => {
        setError(false)
        const newItems = [...items, { key: '', type: 'str' }];
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
    const [sameKey, setSameKey] = useState('')
    useEffect(() => {
        data.required && onValidate(() => {
            setError(false)
            setTimeout(() => {
                setError(true)
            }, 100);

            let msg = ''
            const map = {}
            items.some(item => {
                if (item.key === '') {
                    msg = t('variableNameCannotBeEmpty')
                    return true
                } else if (!/^[a-zA-Z_][a-zA-Z0-9_]{1,50}$/.test(item.key)) {
                    msg = t('variableNameInvalid')
                    return true
                } else if (item.key.length > 50) {
                    msg = t('variableNameTooLong')
                    return true
                } else if (map[item.key]) {
                    msg = t('variableNameDuplicate')
                    setSameKey(item.key)
                    return true
                } else {
                    map[item.key] = true
                    setSameKey('-')
                }
            })
            return msg || false
        })

        return () => onValidate(() => { })
    }, [data.value])

    return (
        <div className="nowheel max-h-80 overflow-y-auto">
            {items.map((item, index) => (
                <Item
                    key={index}
                    sameKey={sameKey}
                    validate={error}
                    nodeId={nodeId}
                    item={item}
                    index={index}
                    onUpdateItem={handleUpdateItem}
                    onDeleteItem={handleDeleteItem}
                />
            ))}
            <Button onClick={handleAddItem} variant="outlined" className="border-primary text-primary mt-2 h-8" color="default">
                {t('addNewParameter')}
            </Button>
        </div>
    );
}

