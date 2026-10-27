// @ts-strict-ignore
import { Button, Input, Select } from '@bisheng/ui';


import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";
import { FlowTooltip as Tip } from "@/pages/BuildPage/flow/FlowTooltip";
import { findInvalidRefItems, updateVariableNameByCode } from "@/util/flowUtils";
import { Outlined } from "bisheng-icons";

import { useEffect,useState } from "react";
import { useTranslation } from 'react-i18next';
import useFlowStore from "../../flowStore";
import { useUpdateVariableState } from "../flowNodeStore";
import SelectVar from "./SelectVar";

const Item = ({ nodeId, validate, sameKey, item, index, onUpdateItem, onDeleteItem, refOnly = false, fixedKeys = false, refInvalid = false }) => {
    const { t } = useTranslation('flow');
    const selectLabels = useSelectLabels();
    const typeOptions = [
        { value: 'ref', label: t('reference') },
        { value: 'input', label: t('input') },
    ];

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
        // Same rule as the list check below: one to 50 characters.
        if (!/^[a-zA-Z_][a-zA-Z0-9_]{0,49}$/.test(item.key)) {
            setError(true);
        } else {
            setError(false);
        }
    }, [validate])

    return (
        <div className="flex gap-1 items-center mb-1">
            {/* key */}
            <Input value={item.key} placeholder={t('parameterName')} onChange={handleKeyChange} readOnly={fixedKeys} className={`${!fixedKeys && (error || sameKey === item.key) && 'border-red-500'} h-8`} />
            {/* type */}

{!refOnly && <Select
                {...selectLabels}
                options={typeOptions}
                value={item.type || null}
                onChange={(v) => {
                    // Re-picking the current type is a no-op (Radix never fired for it).
                    const next = v == null ? '' : String(v);
                    if (next !== item.type) handleTypeChange(next);
                }}
                placeholder={t('type')}
                aria-label={t('type')}
                className="nodrag w-24 shrink-0"
            />}
            {/* value */}
            {item.type === 'ref' ? <SelectVar nodeId={nodeId} itemKey={''} onSelect={(E, v) => {
                onUpdateItem(index, { ...item, label: `${E.name}/${v.label}`, value: `${E.id}.${v.value}` })
            }}>
                <Tip content={item.label} side="top">
                    <div className={`no-drag nowheel group flex h-8 w-full items-center justify-between whitespace-nowrap rounded-md border ${refInvalid ? 'border-red-500' : 'border-input'} bg-search-input px-3 py-1 text-sm shadow-sm ring-offset-background placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50 [&>span]:line-clamp-1 data-[placeholder]:text-gray-400`}>
                        {item.label ? <span className="flex items-center">
                            {item.label}
                        </span> : <span className="bisheng-label">{t('value')}</span>}
                        <Outlined.Down className="h-5 w-5 min-w-5 opacity-80 group-data-[state=open]:rotate-180" />
                    </div>
                </Tip>
            </SelectVar> : <Input value={item.value} placeholder={t('value')} onChange={handleValueChange} className={"h-8"} />}
            {!fixedKeys && <Outlined.Delete size={16} onClick={() => onDeleteItem(index)} className="min-w-5 hover:text-red-600 cursor-pointer" />}
        </div>
    );
};


interface CodeInputItemProps {
    nodeId: string
    data: any // eslint-disable-line @typescript-eslint/no-explicit-any -- node param shape is untyped
    onValidate: (validate: () => string | false) => void
    /** Registers the pre-run check that referenced variables still exist. */
    onVarEvent?: (validate: () => Promise<string> | void) => void
    onChange: (items: CodeInputValue[]) => void
    i18nPrefix: string
    /** Only "reference" values: hides the reference/input switch. */
    refOnly?: boolean
    /** Extra check per name; returns an error message or false. */
    validateName?: (name: string) => string | false
    /** Names come from elsewhere: no add, delete or rename. */
    fixedKeys?: boolean
}

type CodeInputValue = { key: string, type: string, label: string, value: string }

export default function CodeInputItem({ nodeId, data: paramItem, onValidate, onVarEvent, onChange, refOnly = false, validateName, fixedKeys = false }: CodeInputItemProps) {
    const { t } = useTranslation('flow');
    const [items, setItems] = useState(paramItem.value);

    const handleAddItem = () => {
        setError(false)
        const newItems: CodeInputValue[] = [...items, { key: '', type: 'ref', label: '', value: '' }];
        setItems(newItems);
        onChange(newItems);
    };

    const handleUpdateItem = (index, newItem) => {
        setInvalidIndexes([])
        const newItems = items.map((item, i) => (i === index ? newItem : item));
        setItems(newItems);
        onChange(newItems);
    };

    const handleDeleteItem = (index) => {
        setInvalidIndexes([])
        const newItems = items.filter((_, i) => i !== index);
        setItems(newItems);
        onChange(newItems);
    };

    const [error, setError] = useState(false)
    const [sameKey, setSameKey] = useState('')
    useEffect(() => {
        paramItem.required && onValidate(() => {
            setError(false)
            setTimeout(() => {
                setError(true)
            }, 100);

            let msg = ''
            const map = {}
            items.some(item => {
                if (fixedKeys) return false
                const extraError = validateName?.(item.key)
                if (item.key === '') {
                    msg = t('variableNameCannotBeEmpty')
                    return true
                } else if (!/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(item.key)) {
                    msg = t('variableNameInvalid')
                    return true
                } else if (item.key.length > 50) {
                    msg = t('variableNameTooLong')
                    return true
                } else if (map[item.key]) {
                    msg = t('variableNameDuplicate')
                    setSameKey(item.key)
                    return true
                } else if (extraError) {
                    msg = extraError
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
    }, [paramItem.value])

    // Referenced variables must still exist when the flow runs
    const { flow } = useFlowStore();
    const [invalidIndexes, setInvalidIndexes] = useState<number[]>([])
    useEffect(() => {
        if (!onVarEvent) return
        onVarEvent(() => {
            const { error, indexes } = findInvalidRefItems(nodeId, flow.nodes, paramItem.value)
            setInvalidIndexes(indexes)
            return Promise.resolve(error)
        })
        return () => onVarEvent(() => { })
    }, [nodeId, onVarEvent, paramItem, items, flow])

    // Update Preset Questions
    // const [_, forceUpdate] = useState(false)
    const [updateVariable] = useUpdateVariableState()
    useEffect(() => {
        if (!updateVariable) return
        const { action, question } = updateVariable
        if (action === 'd') {
            // delete paramItem.varZh[key]
            // setValue('')
            // onChange('')
        } else if (action === 'u') {
            const newItems = updateVariableNameByCode(paramItem, updateVariable)
            if (newItems) {
                setItems(newItems)
                onChange(newItems)
            }
        }
    }, [updateVariable])

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
                    refOnly={refOnly}
                    fixedKeys={fixedKeys}
                    refInvalid={invalidIndexes.includes(index)}
                />
            ))}
            {!fixedKeys && <Button onClick={handleAddItem} variant="outlined" className="border-primary text-primary mt-2 h-8" color="default">
                {t('addNewParameter')}
            </Button>}
        </div>
    );
}
