import { Label } from "@/components/bs-ui/label"
import { Switch } from "@/components/bs-ui/switch"
import { QuestionTooltip } from "@/components/bs-ui/tooltip"
import { useState } from "react"

export default function SwitchItem({ data, onChange }) {
    const [value, setValue] = useState(data.value)

    return <div className='node-item mb-4 flex justify-between' data-key={data.key}>
        <Label className="flex items-center bisheng-label">
            {data.label}
            {data.help && <QuestionTooltip content={data.help} />}
        </Label>
        <Switch checked={value} onCheckedChange={(bln) => {
            setValue(bln)
            onChange(bln)
        }} />
    </div>
};
