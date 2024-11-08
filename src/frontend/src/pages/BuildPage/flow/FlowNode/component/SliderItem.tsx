import { Label } from "@/components/bs-ui/label";
import { Slider } from "@/components/bs-ui/slider";
import { Switch } from "@/components/bs-ui/switch";
import React from "react";

export default function SliderItem({ data, onChange }) {
    const [value, setValue] = React.useState(data.value * 100)

    return <div className='node-item mb-4' data-key={data.key}>
        <Label className='bisheng-label'>{data.label}</Label>
        <div className="flex gap-4 mt-2">
            <Slider
                name="slider"
                value={[value]}
                min={0}
                max={200}
                step={10}
                onValueChange={(v) => {
                    setValue(v[0])
                    onChange(v[0] / 100)
                }}
            />
            <span className="w-10">{value / 100}</span>
        </div>
    </div>
};

export const SwitchSliderItem = ({ data, onChange }) => {
    const [value, setValue] = React.useState({
        flag: data.value.flag,
        value: data.value.number
    })

    return <div className='node-item mb-4' data-key={data.key}>
        <div className="flex justify-between items-center">
            <Label className='bisheng-label'>{data.label}</Label>
            <Switch checked={value.flag} onCheckedChange={(v) => {
                const newValue = { ...value, flag: v }
                setValue(newValue)
                onChange(newValue)
            }} />
        </div>
        <div className="flex gap-4 mt-2">
            <Slider
                className={value.flag ? '' : 'opacity-50 cursor-no-drop'}
                disabled={!value.flag}
                name="slider"
                value={[value.value]}
                min={0}
                max={100}
                step={1}
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