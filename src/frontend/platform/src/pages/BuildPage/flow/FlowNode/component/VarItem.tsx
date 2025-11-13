import { Badge } from "@/components/bs-ui/badge";
import { Label } from "@/components/bs-ui/label";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import { ChevronUp } from "lucide-react";
import { useEffect, useState } from "react";
import { useUpdateVariableState } from "../flowNodeStore";

export default function VarItem({ data: paramItem }) {
    const [open, setOpen] = useState(true)
    // Update Preset Questions 
    const [_, forceUpdate] = useState(false)
    const [updateVariable] = useUpdateVariableState()
    useEffect(() => {
        if (!updateVariable) return
        const { action, question } = updateVariable
        if (action === 'd') {
            // delete paramItem.varZh[key]
            // const newValues = paramItem.value.filter(el => el !== key)
            // setValue(newValues);
            // onChange(newValues);
        } else if (action === 'u' && question && Array.isArray(paramItem.value)) {
            const regOutput = new RegExp(`preset_question_${question.id}$`)
            paramItem.value.reduce((change, item) => {
                if (regOutput.test(item.key)) {
                    item.label = item.label.replace(/_[^_]+$/, '_' + question.name)
                    return true
                }
                return change
            }, false)
            forceUpdate(!_)
        }
    }, [updateVariable])

    if (Array.isArray(paramItem.value) && paramItem.value.length > 0) return <div className="mb-2">
        <div className="flex justify-between items-center">
            <Label className="bisheng-label">
                {paramItem.label}
                {paramItem.help && <QuestionTooltip content={paramItem.help} />}
            </Label>
            <ChevronUp className={open ? 'rotate-180' : ''} onClick={() => setOpen(!open)} />
        </div>
        <div className={open ? 'block' : 'hidden'}>
            {
                paramItem.value.map((item, index) =>
                    <Badge key={item.key} variant="outline" className="bg-[#E6ECF6] text-[#2B53A0] ml-1 mt-1">{item.label}</Badge>
                )
            }
        </div>
    </div>

    return <div className="mb-4 flex justify-between items-center">
        <Label className="flex items-center bisheng-label">
            {paramItem.label}
            {paramItem.help && <QuestionTooltip content={paramItem.help} />}
        </Label>
        <Badge variant="outline" className="bg-[#E6ECF6] text-[#2B53A0]">{paramItem.key}</Badge>
    </div>
};
