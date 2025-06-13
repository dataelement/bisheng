import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Filter } from "lucide-react";

export default function FilterByUsergroup({ value, onChange }) {
    const { t } = useTranslation()
    const [filter, setFilter] = useState(999)
    return <div className="w-[200px] relative">
        <Select value={value} onValueChange={onChange}>
            <SelectTrigger className="border-none w-16">
                <Filter size={16} className={`cursor-pointer ${filter === 999 ? '' : 'text-gray-950'}`} />
            </SelectTrigger>
            <SelectContent className="max-w-[220px] break-all">
                <SelectGroup style={{width: 220}}>
                    <SelectItem value="1">
                        好评数（定义一）
                        <QuestionTooltip className="relative top-0.5 ml-1" side="bottom" content="好评数=所有点赞消息数之和" />
                    </SelectItem>
                    <SelectItem value="2">
                        好评数（定义二）
                        <QuestionTooltip className="relative top-0.5 ml-1" content={<div>好评数=所有非点踩<p>(含无交互)消息数之和</p></div>} />
                    </SelectItem>
                </SelectGroup>
            </SelectContent>
        </Select>
    </div>
};
