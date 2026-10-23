import { Label } from "@/components/bs-ui/label";
import { AppHint as QuestionTooltip } from "@/pages/BuildPage/components/AppHint";
import { Slider } from "@bisheng/ui";
import React from "react";
import { useTranslation } from "react-i18next";

// The value is read back exactly, so the slider carries a number box (Slider spec §5.1);
// `nodrag` keeps the canvas from panning the node while the thumb is dragged.
export default function SliderItem({ data, onChange, i18nPrefix }) {
    const [value, setValue] = React.useState(data.value)
    const { t } = useTranslation('flow')
    const label = t(`${i18nPrefix}label`)

    return <div className='node-item mb-4' data-key={data.key}>
        <Label className='flex items-center bisheng-label'>
            {t(`${i18nPrefix}label`)}
            {data.help && <QuestionTooltip content={t(`${i18nPrefix}help`)} />}
        </Label>
        <div className="nodrag mt-2">
            <Slider
                name="slider"
                value={value}
                min={data.scope?.[0] || 0}
                max={data.scope?.[1] || 10}
                step={data.step || 1}
                valueDisplay="input"
                thumbLabel={label}
                inputProps={{
                    'aria-label': label,
                    increaseLabel: t('bs:sharedUi.increase'),
                    decreaseLabel: t('bs:sharedUi.decrease'),
                }}
                onValueChange={(v) => {
                    setValue(v)
                    onChange(v)
                }}
            />
        </div>
    </div>
};

export const SwitchSliderItem = ({ data, onChange, i18nPrefix }) => {
    const { t } = useTranslation('flow')
    const label = t(`${i18nPrefix}label`)
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
        <div className="nodrag mt-2">
            <Slider
                disabled={!value.flag}
                name="slider"
                value={value.value}
                min={data.scope?.[0] || 0}
                max={data.scope?.[1] || 10}
                step={data.step || 1}
                valueDisplay="input"
                thumbLabel={label}
                inputProps={{
                    'aria-label': label,
                    increaseLabel: t('bs:sharedUi.increase'),
                    decreaseLabel: t('bs:sharedUi.decrease'),
                }}
                onValueChange={(v) => {
                    const newValue = { ...value, value: v }
                    setValue(newValue)
                    onChange(newValue)
                }}
            />
        </div>
    </div>
}