import { Input } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import { useState } from "react";

export default function InputItem({ type = 'text', data, onChange }) {
    const [value, setValue] = useState(data.value || '')

    return <div className='node-item mb-4' data-key={data.key}>
        <Label className="flex items-center bisheng-label">
            {data.label}
            {data.help && <QuestionTooltip content={data.help} />}
        </Label>
        <Input className="mt-2 nodrag"
            value={value}
            type={type}
            onChange={(e) => {
                setValue(e.target.value);
                onChange(e.target.value);
            }}
        ></Input>
    </div>
};
