import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogContent, DialogTitle, DialogTrigger } from "@/components/bs-ui/dialog";
import { Input } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { useEffect, useState } from "react";
import ReportWordEdit from "./ReportWordEdit";

export default function ReportItem({ nodeId, data, onChange, onValidate }) {
    const [value, setValue] = useState({
        name: data.value.file_name || '',
        key: data.value.version_key || ''
    })

    const handleChange = (key) => {
        setValue({ ...value, key })
        onChange({
            file_name: value.name,
            version_key: key
        })
    }

    const [error, setError] = useState(false)
    useEffect(() => {
        data.required && onValidate(() => {
            if (!data.value.file_name) {
                setError(true)
                return data.label + '不可为空'
            }
            setError(false)
            return false
        })

        return () => onValidate(() => { })
    }, [data.value])
    return <div className='node-item mb-4 nodrag' data-key={data.key}>
        <Label className='bisheng-label'>{data.label}</Label>
        <Input value={value.name}
            className={`mt-2 ${error && 'border-red-500'}`}
            placeholder={data.placeholder}
            maxLength={100}
            onChange={(e) => {
                setValue({ ...value, name: e.target.value });
                onChange({
                    file_name: e.target.value,
                    version_key: value.key
                })
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
                    <ReportWordEdit nodeId={nodeId} versionKey={value.key} onChange={handleChange} />
                </DialogTitle>
            </DialogContent>
        </Dialog>
    </div>
};