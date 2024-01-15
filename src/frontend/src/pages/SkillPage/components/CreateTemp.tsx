import { useContext, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Textarea } from "../../../components/ui/textarea";
import { alertContext } from "../../../contexts/alertContext";
import { createTempApi } from "../../../controllers/API";
import { FlowType } from "../../../types/flow";
import { captureAndAlertRequestErrorHoc } from "../../../controllers/request";

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

    return <dialog className={`modal bg-blur-shared ${open ? 'modal-open' : 'modal-close'}`} onClick={() => setOpen(false)}>
        <form method="dialog" className="max-w-[600px] flex flex-col modal-box bg-[#fff] shadow-lg dark:bg-background" onClick={e => e.stopPropagation()}>
            <button className="btn btn-sm btn-circle btn-ghost absolute right-2 top-2" onClick={() => setOpen(false)}>✕</button>
            <h3 className="font-bold text-lg mb-4">{t('skills.createTemplate')}</h3>
            <div className="flex flex-wrap flex-col gap-4">
                <div className="grid grid-cols-4 items-center gap-4">
                    <Label htmlFor="name" className="text-right">{t('skills.skillName')}</Label>
                    <Input id="name" value={data.name} onChange={(e) => setData({ ...data, name: e.target.value })} className="col-span-2" />
                </div>
                <div className="grid grid-cols-4 items-center gap-4">
                    <Label htmlFor="username" className="text-right">{t('skills.description')}</Label>
                    <Textarea id="name" value={data.description} onChange={(e) => setData({ ...data, description: e.target.value })} className="col-span-2" />
                </div>
                <Button type="submit" className="h-8 w-[400px] rounded-full mt-6 mx-auto" onClick={handleSubmit}>{t('create')}</Button>
            </div>
        </form>
    </dialog>
};
