import { Button } from "@/components/bs-ui/button";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";
import InputComponent from "@/components/inputComponent";
import InputFileComponent from "@/components/inputFileComponent";
import { WorkflowNodeParam } from "@/types/flow";
import { useRef } from "react";
import { useTranslation } from "react-i18next";

const enum FormItemType {
    Text = 'text',
    File = 'file',
    Select = 'select'
}

const InputForm = ({ data, onSubmit }: { data: WorkflowNodeParam, onSubmit: (data: any) => void }) => {
    const { t } = useTranslation()

    const formDataRef = useRef(data.value.reduce((map, item) => {
        map[item.key] = { key: item.key, type: item.type, label: item.value, fileName: '', value: '' }
        return map
    }, {}))

    const handleChange = (item, value) => {
        formDataRef.current[item.key].value = value
    }

    const updataFileName = (item, fileName) => {
        formDataRef.current[item.key].fileName = fileName
    }

    const submit = () => {
        const valuesObject = {}
        let stringObject = ""

        Object.keys(formDataRef.current).forEach((key: string) => {
            const item = formDataRef.current[key]
            valuesObject[key] = item.value
            stringObject += `${item.label}:${item.type === FormItemType.File ? item.fileName : item.value}\n`
        })

        onSubmit([valuesObject, stringObject])
    }

    return <div className="flex flex-col gap-6 rounded-xl p-4 ">
        <div className="max-h-[520px] overflow-y-auto">
            {
                data.value.map((item, i) => (
                    <div key={item.id} className="w-full text-sm">
                        {item.value}
                        {/* <span className="text-status-red">{item.required ? " *" : ""}</span> */}
                        <div className="mt-2">
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
                                            <Select onValueChange={(val) => handleChange(item, val)}>
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
                                        return (
                                            <InputFileComponent
                                                isSSO
                                                disabled={false}
                                                placeholder={t('report.fileRequired')}
                                                value={''}
                                                onChange={(name) => updataFileName(item, name)}
                                                fileTypes={["png", "jpg", "jpeg", "doc", "docx", "ppt", "pptx", "xls", "xlsx", "txt", "md", "html", "pdf"]}
                                                suffixes={['xxx']}
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
        </div>
        <Button size="sm" onClick={submit}>{t('report.start')}</Button>
    </div>
};

export default InputForm