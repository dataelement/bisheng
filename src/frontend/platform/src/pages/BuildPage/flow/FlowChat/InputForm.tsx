import { Button } from "@/components/bs-ui/button";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";
import MultiSelect from "@/components/bs-ui/select/multi";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import InputComponent from "@/components/inputComponent";
import InputFileComponent from "@/components/inputFileComponent";
import { WorkflowNodeParam } from "@/types/flow";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { FileTypes } from "./ChatInput";

const enum FormItemType {
    Text = 'text',
    File = 'file',
    Select = 'select'
}

const InputForm = ({ data }: { data: WorkflowNodeParam }) => {
    const { t } = useTranslation()

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

    const { message } = useToast()
    const submit = () => {
        const valuesObject = {}
        let stringObject = ""
        const errors = []

        Object.keys(formDataRef.current).forEach((key: string) => {
            const fieldData = formDataRef.current[key]
            const required = data.value.find(item => item.key === key).required
            if (required && !fieldData.value) {
                errors.push(t('report.requiredField', { label: fieldData.label }));
            }
            valuesObject[key] = fieldData.value
            stringObject += `${fieldData.label}:${fieldData.type === FormItemType.File ? fieldData.fileName : fieldData.value}\n`
        })

        if (errors.length) {
            return message({
                description: errors,
                variant: 'warning'
            })
        }
        const myEvent = new CustomEvent('inputFormEvent', {
            detail: {
                data: valuesObject,
                msg: stringObject
            }
        });
        document.dispatchEvent(myEvent);
    }

    const [multiVal, setMultiVal] = useState([])
    return <div className="flex w-full">
        <div className="max-w-[90%] min-w-96">
            <div className="min-h-8 px-6 py-4 rounded-2xl bg-[#F5F6F8] dark:bg-[#313336]">
                {
                    data.value.map((item, i) => (
                        <div key={item.id} className="w-full text-sm bisheng-label">
                            {item.required && <span className="text-red-500">*</span>}
                            {item.value}
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
                                                    // value={item.value}
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
                                                        <SelectContent>
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
                                            const fileAccept = item.file_types;
                                            const filesTypes = [];
                                            if (fileAccept.includes('image')) {
                                                filesTypes.push(...FileTypes.IMAGE);
                                            }
                                            if (fileAccept.includes('file')) {
                                                filesTypes.push(...FileTypes.FILE);
                                            } 
                                            if (fileAccept.includes('audio')) {
                                                filesTypes.push(...FileTypes.AUDIO);
                                            }
                                            return (
                                                <InputFileComponent
                                                    isSSO
                                                    disabled={false}
                                                    placeholder={t('report.fileRequired')}
                                                    value={''}
                                                    multiple={item.multiple}
                                                    onChange={(name) => updataFileName(item, name)}
                                                    // fileTypes={FileTypes[item.file_type.toUpperCase()]}
                                                    suffixes={filesTypes}
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
                <Button size="sm" className="w-full" onClick={submit}>{t('report.start')}</Button>
            </div>
        </div>
    </div>
};

export default InputForm
