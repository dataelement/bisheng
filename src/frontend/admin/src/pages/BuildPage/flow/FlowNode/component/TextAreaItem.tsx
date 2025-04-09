import { Textarea } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { useState } from "react";

export default function TextAreaItem({ data, onChange }) {
    const [value, setValue] = useState(data.value || '')

    return <div className='node-item mb-4' data-key={data.key}>
        <Label className='bisheng-label'>{data.label}</Label>
        <Textarea value={value}
            className="nodrag mt-2"
            placeholder={data.placeholder || ''}
            onChange={(e) => {
                setValue(e.target.value);
                onChange(e.target.value);
            }}
        ></Textarea>
    </div>
};
