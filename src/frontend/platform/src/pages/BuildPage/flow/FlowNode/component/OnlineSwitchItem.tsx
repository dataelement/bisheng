import { Label } from "@/components/bs-ui/label"
import { Switch } from "@/components/bs-ui/switch"
import { QuestionTooltip } from "@/components/bs-ui/tooltip"
import useModelStore, { MODEL_TYPE } from "@/store/useModelStore"
import { useMemo, useState } from "react"

export default function OnlineSwitchItem({ data, onChange, node, item }) {
    const { models, agentModels } = useModelStore()

    const [value, setValue] = useState(data.value)
    
    const modelList = node.type === 'agent' ? agentModels : models;
    const modelId = node.group_params?.[1]?.params?.[0]?.value;
    let hasOnlineCapacity =  modelList.find(item => item.id === modelId)?.hasOnlineCapacity;
    
    
    if (!hasOnlineCapacity) return false;

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
