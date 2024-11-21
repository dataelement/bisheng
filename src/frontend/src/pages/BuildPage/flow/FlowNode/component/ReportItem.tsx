import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogContent, DialogTitle, DialogTrigger } from "@/components/bs-ui/dialog";
import { Input } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { useEffect, useState } from "react";
import ReportWordEdit from "./ReportWordEdit";

export default function ReportItem({ nodeId, data, onChange, onValidate }) {
    const [value, setValue] = useState(data.value.name || '')

    const handleChange = ({ key, path }) => {
        onChange({
            name: value,
            key,
            path
        })
    }

    const [error, setError] = useState(false)
    useEffect(() => {
        data.required && onValidate(() => {
            if (!data.value.name) {
                setError(true)
                return data.label + '不可为空'
            }
            setError(false)
            return false
        })

        return () => onValidate(() => {})
    }, [data.value])
    return <div className='node-item mb-4 nodrag' data-key={data.key}>
        <Label className='bisheng-label'>{data.label}</Label>
        <Input value={value}
            className={`mt-2 ${error && 'border-red-500'}`}
            placeholder={data.placeholder}
            maxLength={100}
            onChange={(e) => {
                setValue(e.target.value);
                // onChange(e.target.value);
            }}
        ></Input>

        <Dialog >
            <DialogTrigger asChild>
                <Button variant="outline" className="border-primary text-primary mt-2 h-8">
                    编辑报告模板
                </Button>
            </DialogTrigger>
            <DialogContent className="size-full lg:max-w-full ">
                {/* <DialogHeader> </DialogHeader> */}
                <DialogTitle className="flex items-center">
                    <ReportWordEdit nodeId={nodeId} data={data.value} onChange={handleChange} />
                </DialogTitle>
            </DialogContent>
        </Dialog>
    </div>
};