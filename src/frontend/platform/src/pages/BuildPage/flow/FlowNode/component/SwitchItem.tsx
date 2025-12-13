import { Label } from "@/components/bs-ui/label"
import { Switch } from "@/components/bs-ui/switch"
import { QuestionTooltip } from "@/components/bs-ui/tooltip"
import { useState } from "react"
import { useTranslation } from "react-i18next"

export default function SwitchItem({ data, onChange, i18nPrefix }) {
    const [value, setValue] = useState(data.value)
    const { t } = useTranslation('flow')

    return <div className='node-item mb-4 flex justify-between' data-key={data.key}>
        <Label className="flex items-center bisheng-label">
            {t(`${i18nPrefix}label`)}
            {data.help && <QuestionTooltip content={t(`${i18nPrefix}help`)} />}
        </Label>
        <Switch checked={value} onCheckedChange={(bln) => {
            setValue(bln)
            onChange(bln)
        }} />
    </div>
};
