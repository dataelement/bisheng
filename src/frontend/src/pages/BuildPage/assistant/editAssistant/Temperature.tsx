import { ButtonNumber } from "@/components/bs-ui/button";
import { Slider } from "@/components/bs-ui/slider";

export default function Temperature({ value, onChange }) {

    const props = { max: 2, min: 0, step: 0.1 }

    return <div className="flex gap-4 mt-2">
        <Slider
            name="slider"
            value={[value]}
            onValueChange={(v) => onChange(v[0])}
            {...props}
        />
        <ButtonNumber
            value={value}
            onChange={onChange}
            {...props}
        />
    </div>
};
