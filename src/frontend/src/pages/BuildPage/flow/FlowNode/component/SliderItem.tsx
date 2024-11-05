import { Label } from "@/components/bs-ui/label";
import { Slider } from "@/components/bs-ui/slider";
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
