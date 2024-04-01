import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";
import { getAssistantModelsApi } from "@/controllers/API/assistant";
import { useEffect, useState } from "react";

export default function ModelSelect({ value, onChange }) {

    const [configServers, setConfigServers] = useState([])
    const loadModels = async () => {
        const data = await getAssistantModelsApi()
        setConfigServers(data)
    }

    useEffect(() => {
        loadModels()
    }, [])

    return <Select name="model" required value={value} onValueChange={onChange}>
        <SelectTrigger className="mt-2">
            <SelectValue placeholder="选择一个模型" ></SelectValue>
        </SelectTrigger>
        <SelectContent>
            <SelectGroup>
                {
                    configServers.map(server => <SelectItem key={server.id} value={server.model_name}>{server.model_name}</SelectItem>)
                }
            </SelectGroup>
        </SelectContent>
    </Select>
};
