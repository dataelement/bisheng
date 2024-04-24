import { Dialog, DialogClose, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { useContext, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "../../../components/bs-ui/button";
import { Input, Textarea } from "../../../components/bs-ui/input";
import { alertContext } from "../../../contexts/alertContext";
import { createTempApi } from "../../../controllers/API";
import { captureAndAlertRequestErrorHoc } from "../../../controllers/request";
import { FlowType } from "../../../types/flow";

export default function CreateTemp({ flow, open, setOpen, onCreated }: { flow: FlowType, open: boolean, setOpen: any, onCreated?: any }) {
    const { setErrorData, setSuccessData } = useContext(alertContext);
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

    const handleSubmit = () => {
        const errorlist = []
        const { name, description } = data
        if (!name) errorlist.push(t('skills.skillNameRequired'))
        if (name.length > 30) errorlist.push(t('skills.skillNameTooLong'))
        if (!description) errorlist.push(t('skills.skillDescRequired')) // 加些描述能够快速让别人理解您创造的技能')
        if (description.length > 200) errorlist.push(t('skills.skillDescTooLong'))
        if (errorlist.length) setErrorData({
            title: t('skills.errorTitle'),
            list: errorlist,
        });
        // rq
        captureAndAlertRequestErrorHoc(createTempApi({ ...data, flow_id: flow.id }).then(res => {
            setOpen(false)
            setSuccessData({ title: t('skills.createSuccessTitle') });
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
                    <label htmlFor="name" className="bisheng-label">{t('skills.skillName')}</label>
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
