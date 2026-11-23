import { Label } from "@/components/bs-ui/label";
import { AppHint as QuestionTooltip } from "@/pages/BuildPage/components/AppHint";
import { Switch } from "@bisheng/ui";
import { useState } from "react";
import { useTranslation } from "react-i18next";

export default function SwitchItem({ data, onChange, i18nPrefix }) {
    const [value, setValue] = useState(data.value)
    const { t } = useTranslation('flow')

    return <div className='node-item mb-4' data-key={data.key}>
        <div className='flex justify-between'>
            <Label className="flex items-center bisheng-label">
                {t(`${i18nPrefix}label`)}
                {data.help && <QuestionTooltip content={t(`${i18nPrefix}help`)} />}
            </Label>
            <Switch checked={value} onCheckedChange={(bln) => {
                setValue(bln)
                onChange(bln)
            }} />
        </div>
        {/* Optional always-visible explanation under the switch (workflow memory, AC-75) */}
        {data.desc && <p className="mt-1 text-xs leading-5 text-muted-foreground">{t(`${i18nPrefix}desc`)}</p>}
    </div>
};
