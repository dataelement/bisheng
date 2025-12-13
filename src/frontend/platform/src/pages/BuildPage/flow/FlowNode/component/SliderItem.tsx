import { Label } from "@/components/bs-ui/label";
import { Slider } from "@/components/bs-ui/slider";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import React from "react";
import { useTranslation } from "react-i18next";

export default function SliderItem({ data, onChange, i18nPrefix }) {
    const [value, setValue] = React.useState(data.value)
    const { t } = useTranslation('flow')

    return <div className='node-item mb-4' data-key={data.key}>
        <Label className='flex items-center bisheng-label'>
            {t(`${i18nPrefix}label`)}
            {data.help && <QuestionTooltip content={t(`${i18nPrefix}help`)} />}
        </Label>
        <div className="flex gap-4 mt-2">
            <Slider
                name="slider"
                value={[value]}
                min={data.scope?.[0] || 0}
                max={data.scope?.[1] || 10}
                step={data.step || 1}
                onValueChange={(v) => {
                    setValue(v[0])
                    onChange(v[0])
                }}
            />
            <span className="w-10">{value}</span>
        </div>
    </div>
};

export const SwitchSliderItem = ({ data, onChange, i18nPrefix }) => {
    const { t } = useTranslation('flow')
    const [value, setValue] = React.useState({
        flag: data.value.flag,
        value: data.value.value
    })

    return <div className='node-item mb-4' data-key={data.key}>
        <div className="flex justify-between items-center">
            <Label className='flex items-center bisheng-label'>
                {t(`${i18nPrefix}label`)}
                {data.help && <QuestionTooltip content={t(`${i18nPrefix}help`)} />}
            </Label>
            {/* <Switch checked={value.flag} onCheckedChange={(v) => {
                const newValue = { ...value, flag: v }
                setValue(newValue)
                onChange(newValue)
            }} /> */}
        </div>
        <div className="flex gap-4 mt-2">
            <Slider
                className={value.flag ? '' : 'opacity-50 cursor-no-drop'}
                disabled={!value.flag}
                name="slider"
                value={[value.value]}
                min={data.scope?.[0] || 0}
                max={data.scope?.[1] || 10}
                step={data.step || 1}
                onValueChange={(v) => {
                    const newValue = { ...value, value: v[0] }
                    setValue(newValue)
                    onChange(newValue)
                }}
            />
            <span className="w-10">{value.value}</span>
        </div>
    </div>
}