import { Badge } from "@/components/bs-ui/badge";
import { Label } from "@/components/bs-ui/label";
import { ChevronUp } from "lucide-react";
import { useState } from "react";

export default function VarItem({ data }) {
    const [open, setOpen] = useState(false)

    if (Array.isArray(data.value) && data.value.length > 0) return <div className="mb-2">
        <div className="flex justify-between items-center">
            <Label className="bisheng-label">{data.label}</Label>
            <ChevronUp className={open ? 'rotate-180' : ''} onClick={() => setOpen(!open)} />
        </div>
        <div className={open ? 'block' : 'hidden'}>
            {
                data.value.map((item, index) =>
                    <Badge key={item.key} variant="outline" className="bg-[#E6ECF6] text-[#2B53A0] ml-1 mt-1">{item.label}</Badge>
                )
            }
        </div>
    </div>

    return <div className="mb-4 flex justify-between items-center">
        <Label className="bisheng-label">{data.label}</Label>
        <Badge variant="outline" className="bg-[#E6ECF6] text-[#2B53A0]">{data.key}</Badge>
    </div>
};
