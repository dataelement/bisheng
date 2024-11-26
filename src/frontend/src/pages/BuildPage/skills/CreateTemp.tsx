import { Dialog, DialogClose, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { AppType } from "@/types/app";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "../../../components/bs-ui/button";
import { Input, Textarea } from "../../../components/bs-ui/input";
import { createTempApi } from "../../../controllers/API";
import { captureAndAlertRequestErrorHoc } from "../../../controllers/request";
import { FlowType } from "../../../types/flow";

export default function CreateTemp({ flow, open, type, setOpen, onCreated }: { flow: FlowType, type: AppType, open: boolean, setOpen: any, onCreated?: any }) {
    const { t } = useTranslation()

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

    const { message } = useToast()
    const handleSubmit = () => {
        const nameMap = {
            [AppType.FLOW]: '工作流',
            [AppType.SKILL]: '技能名称',
            [AppType.ASSISTANT]: '助手',
        }
        const labelName = nameMap[type]
        const errorlist = []

        const { name, description } = data
        if (!name) errorlist.push(`请填写${labelName}名称`)
        if (name.length > 30) errorlist.push(`${labelName}名称过长，不要超过50字`)
        if (!description) errorlist.push(`加些描述能够快速让别人理解您创造的${labelName}`)
        if (description.length > 200) errorlist.push(`${labelName}描述不可超过 200 字`)
        if (errorlist.length) message({
            variant: 'error',
            description: errorlist
        });

        captureAndAlertRequestErrorHoc(createTempApi({ ...data, flow_id: flow.id }, type).then(res => {
            setOpen(false)
            message({
                variant: 'success',
                description: '模板创建成功'
            })
            onCreated?.()
        }))
    }

    return <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-[625px]">
            <DialogHeader>
                <DialogTitle>{t('skills.createTemplate')}</DialogTitle>
            </DialogHeader>
            <div className="flex flex-col gap-4 py-2">
                <div className="">
                    <label htmlFor="name" className="bisheng-label">{AppType.SKILL === type ? t('skills.skillName') : AppType.ASSISTANT === type ? '助手名称' : '工作流名称'}</label>
                    <Input name="name" className="mt-2" value={data.name} onChange={(e) => setData({ ...data, name: e.target.value })} />
                    {/* {errors.name && <p className="bisheng-tip mt-1">{errors.name}</p>} */}
                </div>
                <div className="">
                    <label htmlFor="roleAndTasks" className="bisheng-label">{t('skills.description')}</label>
                    <Textarea id="name" value={data.description} onChange={(e) => setData({ ...data, description: e.target.value })} className="col-span-2" />
                    {/* {errors.roleAndTasks && <p className="bisheng-tip mt-1">{errors.roleAndTasks}</p>} */}
                </div>
            </div>
            <DialogFooter>
                <DialogClose>
                    <Button variant="outline" className="px-11" type="button" onClick={() => setOpen(false)}>取消</Button>
                </DialogClose>
                <Button type="submit" className="px-11" onClick={handleSubmit}>{t('create')}</Button>
            </DialogFooter>
        </DialogContent>
    </Dialog>
};
