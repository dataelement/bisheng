import { Badge } from "@/components/bs-ui/badge";
import { Input } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { useState } from "react";

export default function HistoryNumItem({ data, onChange }) {

    const [value, setValue] = useState(data.value);

    return <div className="flex items-center mb-2 nodrag -nopan">
        <Label className="bisheng-label">最近</Label>
        <Input type="number" boxClassName="w-20 mx-1" className="h-5" value={value}></Input>
        <Label className="bisheng-label">条链条记录:</Label>
        <Badge variant="outline" className="bg-input text-muted-foreground ml-auto">{data.key}</Badge>
    </div>
};
