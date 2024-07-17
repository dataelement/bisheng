import { Popover, PopoverContent, PopoverTrigger } from "@/components/bs-ui/popover";
import { useRef, useState } from "react";
import { SearchInput } from "@/components/bs-ui/input";
import { Checkbox } from "@/components/bs-ui/checkBox";
import { Label } from "@/components/bs-ui/label";
import { Pencil2Icon } from "@radix-ui/react-icons";
import { Trash2 } from "lucide-react";
import { Input } from "@/components/bs-ui/input";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { useTranslation } from "react-i18next";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";

export default function LabelSelect({labels, children}) {
    const [open, setOpen] = useState(false)
    const [data, setData] = useState(labels)
    const dataRef = useRef(labels)
    const { message } = useToast()
    const { t } = useTranslation()

    const handleEdit = (id) => {
        setData(pre => pre.map(d => d.value === id ? {...d, edit:true} : {...d, edit:false}))
    }
    const handleChange = (e, id) => {
        setData(pre => pre.map(d => d.value === id ? {...d, label:e.target.value} : d))
    }
    const handleSave = (e, id) => {
        if(e.key === 'Enter') {
            setData(pre => pre.map(d => d.value === id ? {...d, edit:false} : d))
            message({
                title: t('prompt'),
                variant: 'success',
                description: '修改成功'
            })
        }
    }
    const handleDelete = (name) => {
        bsConfirm({
            title: t('prompt'),
            desc: `标签【${name}】正在使用中，确认删除？`,
            okTxt: t('system.confirm'),
            onOk(next) {
                console.log('delete')
                next()
            },
        })
    }
    const handleOpenChange = (b) => { // 可用于整体保存
        setOpen(b)
        setData(pre => pre.map(d => ({...d, edit:false}) ))
    }
    const handleSearch = (e) => {
        const key = e.target.value
        const newData = dataRef.current.filter(d => d.label.toUpperCase().includes(key.toUpperCase()))
        setData(newData)
    }

    return <Popover open={open} onOpenChange={handleOpenChange}>
        <PopoverTrigger asChild>
            {children}
        </PopoverTrigger>
        <PopoverContent onClick={(e) => e.stopPropagation()}>
            <div>
                <SearchInput placeholder="搜索标签" onChange={handleSearch} className="w-[240px]"/>
            </div>
            <div className="mt-4 h-[200px] overflow-y-auto">
                {data.map(d => <div className="flex group justify-between h-8 rounded-sm hover:bg-[#F5F5F5]">
                    <div className="flex place-items-center space-x-2">
                        <Checkbox id={d.value} checked={d.selected}/>
                        {
                            d.edit 
                            ? <Input autoFocus className="h-6" type="text" value={d.label} 
                            onChange={(e) => handleChange(e, d.value)}
                            onKeyDown={(e) => handleSave(e, d.value)} />
                            : <Label htmlFor={d.value} className="cursor-pointer">{d.label}</Label>
                        }
                    </div>
                    <div className="flex place-items-center space-x-4 opacity-0 group-hover:opacity-100">
                        <Pencil2Icon className="cursor-pointer" onClick={() => handleEdit(d.value)}/>
                        <Trash2 size={16} onClick={() => handleDelete(d.label)} className="text-gray-600 cursor-pointer" />
                    </div>
                </div>)}
            </div>  
        </PopoverContent>
    </Popover>
}