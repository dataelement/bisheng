import { Input } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import { useState } from "react";

export default function InputItem({ type = 'text', char = false, linefeed = false, data, onChange }) {
    const [value, setValue] = useState(data.value || '')

    // inline style
    if (char) return <div
        className={`node-item mb-4 ${!linefeed ? 'flex items-center justify-between' : ''}`}
        data-key={data.key}
    >
        <Label className="flex items-center bisheng-label">
            {data.label}
            {data.help && <QuestionTooltip content={data.help} />}
        </Label>
        <div className={`nodrag ${char ? 'w-32 flex items-center gap-3' : ''} ${linefeed ? 'mt-2' : ''}`}>
            <Input
                value={value}
                type={type}
                min={data.min}
                onChange={(e) => {
                    setValue(e.target.value);
                    onChange(e.target.value);
                }}
            ></Input>
            <Label className="bisheng-label">字</Label>
        </div>
    </div>

    return <div className='node-item mb-4' data-key={data.key}>
        <Label className="flex items-center bisheng-label">
            {data.label}
            {data.help && <QuestionTooltip content={data.help} />}
        </Label>
        <Input className="mt-2 nodrag"
            value={value}
            type={type}
            min={data.min}
            onChange={(e) => {
                setValue(e.target.value);
                onChange(e.target.value);
            }}
        ></Input>
    </div>
};
