import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";
import { useEffect, useState } from "react";

export default function ModelSelect({ value, onChange }) {

    const [configServers, setConfigServers] = useState([])
    const loadModels = () => {
        // api
        setConfigServers([{ model_name: 'gpt-4-0125-preview' }, { model_name: 'gpt-4-0125-preview2' }])
        // serverListApi().then(setServers)
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
                    configServers.map(server => <SelectItem key={server.model_name} value={server.model_name}>{server.model_name}</SelectItem>)
                }
            </SelectGroup>
        </SelectContent>
    </Select>
};
