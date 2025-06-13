import { X } from "lucide-react";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";

const resultMap = {
    "1": "未审查",
    "2": "通过",
    "3": "违规",
    "4": "审查失败",
}

export default function FilterByResult({ value, onChange, placeholder }) {
    return (
        <div className="w-[200px] relative">
            <Select value={value} onValueChange={(value) => onChange(value)}>
                <SelectTrigger className="w-[200px]">
                    {(value ? <div className="text-foreground inline-flex flex-1 flex-row justify-between items-center">
                    <span>{resultMap[value]}</span>
                    <X className="
                        h-3.5 w-3.5 min-w-3.5 
                        opacity-0 group-hover:opacity-100
                        transition-opacity duration-200
                        bg-black rounded-full
                        flex items-center justify-center
                        "
                    color="#ffffff" onPointerDown={(e) => e.stopPropagation()}  onClick={() => {
                        onChange('')
                    }}></X>
                </div> : placeholder)}
                </SelectTrigger>
                <SelectContent className="max-w-[200px] break-all">
                    <SelectGroup>
                        <SelectItem value={'1'}>未审查</SelectItem>
                        <SelectItem value={'2'}>通过</SelectItem>
                        <SelectItem value={'3'}>违规</SelectItem>
                        <SelectItem value={'4'}>审查失败</SelectItem>
                    </SelectGroup>
                </SelectContent>
            </Select>
        </div>
    );
}
