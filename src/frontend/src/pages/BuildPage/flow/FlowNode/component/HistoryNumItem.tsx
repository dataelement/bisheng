import { Badge } from "@/components/bs-ui/badge";
import { Input } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { useState } from "react";

export default function HistoryNumItem({ data, onChange }) {

    const [value, setValue] = useState(data.value);

    return <div className="flex items-center mb-4 nodrag -nopan">
        <Label className="bisheng-label">最近</Label>
        <Input type="number" boxClassName="w-20 mx-1" className="h-5" value={value}></Input>
        <Label className="bisheng-label">条聊天记录:</Label>
        <Badge variant="outline" className="bg-[#E6ECF6] text-[#2B53A0] ml-auto">{data.key}</Badge>
    </div>
};
