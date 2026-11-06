import { Label } from "@/components/bs-ui/label";
import { AppHint as QuestionTooltip } from "@/pages/BuildPage/components/AppHint";
import { Tag } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";

import { useEffect,useState } from "react";
import { useTranslation } from "react-i18next";
import { useUpdateVariableState } from "../flowNodeStore";

export default function VarItem({ data: paramItem, i18nPrefix }) {
    const [open, setOpen] = useState(true)
    const { t } = useTranslation('flow')

    // Update Preset Questions
    const [_, forceUpdate] = useState(false)
    const [updateVariable] = useUpdateVariableState()
    useEffect(() => {
        if (!updateVariable) return
        const { action, question } = updateVariable
        if (action === 'd') {
            // delete paramItem.varZh[key]
            // const newValues = paramItem.value.filter(el => el !== key)
            // setValue(newValues);
            // onChange(newValues);
        } else if (action === 'u' && question && Array.isArray(paramItem.value)) {
            const regOutput = new RegExp(`preset_question_${question.id}$`)
            paramItem.value.reduce((change, item) => {
                if (regOutput.test(item.key)) {
                    item.label = item.label.replace(/_[^_]+$/, '_' + question.name)
                    return true
                }
                return change
            }, false)
            forceUpdate(!_)
        }
    }, [updateVariable])

    if (Array.isArray(paramItem.value) && paramItem.value.length > 0) return <div className="mb-2">
        <div className="outputs flex justify-between items-center">
            <Label className="bisheng-label">
                {t(`${i18nPrefix}label`)}
                {paramItem.help && <QuestionTooltip content={t(`${i18nPrefix}help`)} />}
            </Label>
            <Outlined.Up size={16} className={open ? 'rotate-180' : ''} onClick={() => setOpen(!open)} />
        </div>
        <div className={open ? 'block' : 'hidden'}>
            {
                paramItem.value.map((item, index) =>
                    <Tag size="small" color="brand" key={item.key} className="ml-1 mt-1 max-w-full truncate inline-block">{item.label}</Tag>
                )
            }
        </div>
    </div>

    return <div className="mb-4 flex justify-between items-center">
        <Label className="flex items-center bisheng-label">
            {t(`${i18nPrefix}label`)}
            {paramItem.help && <QuestionTooltip content={t(`${i18nPrefix}help`)} />}
        </Label>
        <Tag size="small" color="brand" className="">{paramItem.key}</Tag>
    </div>
};
