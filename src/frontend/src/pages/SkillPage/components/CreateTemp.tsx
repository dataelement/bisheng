import { useNavigate } from "react-router-dom";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Textarea } from "../../../components/ui/textarea";
import { FlowType } from "../../../types/flow";
import { useContext, useEffect, useState } from "react";
import { alertContext } from "../../../contexts/alertContext";
import { createTempApi } from "../../../controllers/API";

export default function CreateTemp({ flow, open, setOpen, onCreated }: { flow: FlowType, open: boolean, setOpen: any, onCreated?: any }) {
    const { setErrorData, setSuccessData } = useContext(alertContext);

    const [data, setData] = useState({
        name: '',
        description: ''
    })

    useEffect(() => {
        open && setData({
            name: flow.name,
            description: flow.description
        })
    }, [open])

    const handleSubmit = () => {
        const errorlist = []
        const { name, description } = data
        if (!name) errorlist.push('请填写技能名称')
        if (name.length > 30) errorlist.push('技能名称过长，不要超过30字')
        if (!description) errorlist.push('请填写技能描述') // 加些描述能够快速让别人理解您创造的技能')
        if (description.length > 200) errorlist.push('技能描述过长，不要超过200字')
        if (errorlist.length) setErrorData({
            title: "关键信息有误",
            list: errorlist,
        });
        // rq
        createTempApi({ ...data, flow_id: flow.id }).then(res => {
            setOpen(false)
            setSuccessData({ title: '技能创建成功' });
            onCreated?.()
        })
    }

    return <dialog className={`modal bg-blur-shared ${open ? 'modal-open' : 'modal-close'}`} onClick={() => setOpen(false)}>
        <form method="dialog" className="max-w-[600px] flex flex-col modal-box bg-[#fff] shadow-lg dark:bg-background" onClick={e => e.stopPropagation()}>
            <button className="btn btn-sm btn-circle btn-ghost absolute right-2 top-2" onClick={() => setOpen(false)}>✕</button>
            <h3 className="font-bold text-lg mb-4">创建模板</h3>
            <div className="flex flex-wrap flex-col gap-4">
                <div className="grid grid-cols-4 items-center gap-4">
                    <Label htmlFor="name" className="text-right">技能名称</Label>
                    <Input id="name" value={data.name} onChange={(e) => setData({ ...data, name: e.target.value })} className="col-span-2" />
                </div>
                <div className="grid grid-cols-4 items-center gap-4">
                    <Label htmlFor="username" className="text-right">描述</Label>
                    <Textarea id="name" value={data.description} onChange={(e) => setData({ ...data, description: e.target.value })} className="col-span-2" />
                </div>
                <Button type="submit" className="h-8 w-[400px] rounded-full mt-6 mx-auto" onClick={handleSubmit}>创建</Button>
            </div>
        </form>
    </dialog>
};
