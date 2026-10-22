// @ts-strict-ignore
import { Button, Select, toast } from '@bisheng/ui';

import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";

import InputComponent from "@/components/inputComponent";
import InputFileComponent from "@/components/inputFileComponent";
import { locationContext } from "@/contexts/locationContext";
import { WorkflowNodeParam } from "@/types/flow";
import { fileAcceptToInputAccept,normalizeFileAccept } from "@/util/fileAcceptUtils";
import { useContext,useRef,useState } from "react";
import { useTranslation } from "react-i18next";

const enum FormItemType {
    Text = 'text',
    File = 'file',
    Select = 'select'
}

const InputForm = ({ data }: { data: WorkflowNodeParam }) => {
    const { t } = useTranslation()
    const { appConfig } = useContext(locationContext)
    const selectLabels = useSelectLabels()

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
            return toast.show({ type: 'warning', message: errors.filter(Boolean).join('\n') })
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
                                        case FormItemType.Select: {
                                                const options = (item.options || [])
                                                    .filter(el => el.text != null && el.text !== '')
                                                    .map(el => ({ label: String(el.text), value: String(el.text) }))
                                                return item.multiple ?
                                                    <Select
                                                        {...selectLabels}
                                                        multiple
                                                        options={options}
                                                        value={multiVal[item.key] || []}
                                                        placeholder={t('selectOption', { ns: 'flow' })}
                                                        aria-label={item.value}
                                                        onChange={(v) => {
                                                            const vals = v.map(String)
                                                            setMultiVal(prev => ({ ...prev, [item.key]: vals }));
                                                            handleChange(item, vals.join(','))
                                                        }}
                                                    />
                                                    : <Select
                                                        {...selectLabels}
                                                        options={options}
                                                        placeholder={t('selectOption', { ns: 'flow' })}
                                                        aria-label={item.value}
                                                        onChange={(v) => handleChange(item, v == null ? '' : String(v))}
                                                    />
                                        }
                                        case FormItemType.File:
                                            return (
                                                <InputFileComponent
                                                    isSSO
                                                    disabled={false}
                                                    placeholder={t('report.fileRequired')}
                                                    value={''}
                                                    multiple={item.multiple}
                                                    onChange={(name) => updataFileName(item, name)}
                                                    suffixes={fileAcceptToInputAccept(
                                                        normalizeFileAccept(item.file_type, {
                                                            mediaEnabled: !!appConfig.enableMediaUpload,
                                                        }),
                                                    )}
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
                <Button size="small" className="w-full" onClick={submit}>{t('report.start')}</Button>
            </div>
        </div>
    </div>
};

export default InputForm
