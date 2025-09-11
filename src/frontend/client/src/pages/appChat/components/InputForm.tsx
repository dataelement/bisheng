
import { useRef, useState } from "react";
import { Button } from "~/components";
import MultiSelect from "~/components/ui/MultiSelect";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "~/components/ui/Select";
import { useToastContext } from "~/Providers";
import { emitAreaTextEvent, EVENT_TYPE, FileTypes } from "../useAreaText";
import InputComponent from "./InputComponent";
import InputFileComponent from "./InputFileComponent";
import { MessageWarper } from "./MessageBsChoose";

const enum FormItemType {
    Text = 'text',
    File = 'file',
    Select = 'select'
}

interface WorkflowNodeParam {
    /** Unique key */
    key: string;
    /** Optional display */
    label?: string;
    /** type */
    type: string;
    /** value */
    value: any;
    /** placeholder */
    placeholder?: string;
    /** help text */
    help?: string;
    /** tab */
    tab?: string;
    /** required*/
    required?: boolean;
    /**  multiple value */
    multi?: boolean;
    /** Array of options */
    options?: any[];
    test?: string,
    hidden?: boolean;
}

const InputForm = ({ data, flow, logo }: { data: WorkflowNodeParam, flow: any }) => {
    const formDataRef = useRef(data.value.reduce((map, item) => {
        map[item.key] = { key: item.key, type: item.type, label: item.value, fileName: '', value: '' }
        return map
    }, {}))

    const handleChange = (item, value) => {
        if (item.type === FormItemType.File) {
            formDataRef.current[item.key].value = Array.isArray(value) ? value : [value]
        } else {
            formDataRef.current[item.key].value = value
        }
    }

    const updataFileName = (item, fileName) => {
        formDataRef.current[item.key].fileName = fileName
    }

    const { showToast } = useToastContext();
    const submit = () => {
        const valuesObject = {}
        let stringObject = ""
        const errors: string[] = []

        Object.keys(formDataRef.current).forEach((key: string) => {
            const fieldData = formDataRef.current[key]
            const required = data.value.find(item => item.key === key).required
            if (required && !fieldData.value) {
                errors.push(`${fieldData.label} 为必填项，不能为空。`);
            }
            valuesObject[key] = fieldData.value
            stringObject += `${fieldData.label}:${fieldData.type === FormItemType.File ? fieldData.fileName : fieldData.value}\n`
        })

        if (errors.length) {
            return showToast({ message: errors.join('\n'), status: 'warning' });
        }
        emitAreaTextEvent({
            action: EVENT_TYPE.FORM_SUBMIT,
            data: valuesObject,
            nodeId: data.node_id,
            message: stringObject
        })
    }

    const [multiVal, setMultiVal] = useState([])
    return <MessageWarper flow={flow} logo={logo}>
        <div className="max-h-[520px] overflow-y-auto space-y-2">
            {
                data.value.map((item, i) => (
                    <div key={item.id} className="w-full text-sm bisheng-label">
                        {item.value}
                        {item.required && <span className="text-red-500">*</span>}
                        {/* <span className="text-status-red">{item.required ? " *" : ""}</span> */}
                        <div className="mb-2">
                            {(() => {
                                switch (item.type) {
                                    case FormItemType.Text:
                                        return (
                                            <InputComponent
                                                type="textarea"
                                                password={false}
                                                maxLength={10000}
                                                flow={flow}
                                                onChange={(val) => handleChange(item, val)}
                                            />
                                        )
                                    case FormItemType.Select:
                                        return (
                                            item.multiple ?
                                                <MultiSelect
                                                    multiple
                                                    className={''}
                                                    value={multiVal[item.key] || []}
                                                    options={
                                                        item.options.map(el => ({
                                                            label: el.text,
                                                            value: el.text
                                                        }))
                                                    }
                                                    placeholder={'请选择'}
                                                    onChange={(v) => {
                                                        setMultiVal(prev => ({ ...prev, [item.key]: v }));
                                                        handleChange(item, v.join(','))
                                                    }}
                                                >
                                                    {/* {children?.(reload)} */}
                                                </MultiSelect>
                                                : <Select onValueChange={(val) => handleChange(item, val)}>
                                                    <SelectTrigger>
                                                        <SelectValue placeholder="" />
                                                    </SelectTrigger>
                                                    <SelectContent className="bg-white">
                                                        <SelectGroup>
                                                            {item.options.map(el => (
                                                                <SelectItem key={el.text} value={el.text}>
                                                                    {el.text}
                                                                </SelectItem>
                                                            ))}
                                                        </SelectGroup>
                                                    </SelectContent>
                                                </Select>
                                        )
                                    case FormItemType.File:
                                        return (
                                            <InputFileComponent
                                                isSSO
                                                disabled={false}
                                                placeholder="当前文件为空"
                                                value={''}
                                                multiple={item.multiple}
                                                onChange={(name) => updataFileName(item, name)}
                                                // fileTypes={FileTypes[item.file_type.toUpperCase()]}
                                                suffixes={FileTypes[item.file_type.toUpperCase()]}
                                                onFileChange={(val) => handleChange(item, val)}
                                            />
                                        )
                                    default:
                                        return null
                                }
                            })()}
                        </div>
                    </div>
                ))
            }
            <div className="flex justify-end">
                <Button size="sm" className="h-8 px-4" onClick={submit}>开始</Button>
            </div>
        </div>
    </MessageWarper>
};

export default InputForm
