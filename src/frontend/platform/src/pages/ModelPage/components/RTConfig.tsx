// @ts-strict-ignore
import { Button, Input } from '@bisheng/ui';
import { Outlined } from "bisheng-icons";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";


import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow
} from "../../../components/bs-ui/table";
import { addServiceApi, deleteServiceApi, getServicesApi } from "../../../controllers/API";
import { showApiError } from "../../../controllers/request";
import { useCopyText } from "../../../util/hook";

export default function RTConfig({ open, onChange }) {

    const nameRef = useRef(null)
    // const urlRef = useRef(null)
    const ftUrlRef = useRef(null)

    const { services, showAdd, addItem, handleDel, create, setShowAdd } = useRTService(onChange)

    const handleAdd = () => {
        const [name, ftUrl] = [nameRef.current.value, ftUrlRef.current.value]
        if (!name) return
        addItem(name, ftUrl)
        nameRef.current.value = ''
        ftUrlRef.current.value = ''
    }

    const { t } = useTranslation('model')
    const copyText = useCopyText()

    return <Dialog open={open} onOpenChange={onChange}>
        <DialogContent className="max-w-[820px]">
            <DialogHeader>
                <DialogTitle>{t('finetune.rtServiceManagement')}</DialogTitle>
            </DialogHeader>
            <div className="">
                <Table className="w-full">
                    <TableHeader>
                        <TableRow>
                            <TableHead className="w-[200px]">{t('finetune.machineName')}</TableHead>
                            {/* <TableHead>RT{t('finetune.serviceAddress')}</TableHead> */}
                            <TableHead>FT{t('finetune.serviceAddress')}</TableHead>
                            <TableHead className="text-right">{t('bs:operations')}</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {services.map((el) => (
                            <TableRow key={el.id}>
                                <TableCell className="py-2">{el.name}</TableCell>
                                {/* <TableCell className="py-2">
                                    <p className="cursor-pointer" onClick={e => copyText(el.url)}>{el.url}</p>
                                </TableCell> */}
                                <TableCell className="py-2">
                                    <p className="cursor-pointer" onClick={e => copyText(el.ftUrl)}>{el.ftUrl}</p>
                                </TableCell>
                                <TableCell className="py-2 text-right"><Button size="small" variant="link" color="danger" onClick={() => handleDel(el.id)}>{t('bs:delete')}</Button></TableCell>
                            </TableRow>
                        ))}
                        {showAdd && <TableRow>
                            <TableCell><Input ref={nameRef} placeholder="name"></Input></TableCell>
                            {/* <TableCell><Input ref={urlRef} placeholder="IP:PORT"></Input></TableCell> */}
                            <TableCell><Input ref={ftUrlRef} placeholder="IP:PORT"></Input></TableCell>
                            <TableCell>
                                <div className="flex justify-end gap-2">
                                    <Button size="small" variant="link" onClick={handleAdd}>{t('bs:confirmButton')}</Button>
                                    <Button size="small" variant="link" color="default" onClick={() => setShowAdd(false)}>{t('bs:cancel')}</Button>
                                </div>
                            </TableCell>
                        </TableRow>}
                    </TableBody>
                </Table>
            </div>
            <DialogFooter>
                <div className="flex justify-start mt-4">
                    <Button variant="outlined" className="flex" onClick={() => setShowAdd(true)} color="default"><Outlined.Plus className="mr-2 size-5" />{t('bs:create')}</Button>
                </div>
            </DialogFooter>
        </DialogContent>
    </Dialog>
};

type SERVICE = {
    id: number,
    create_time?: string,
    update_time?: string,
    url?: string,
    ftUrl: string,
    remark?: string,
    name: string
}

const useRTService = (onChange) => {
    const [services, setServices] = useState<SERVICE[]>([])
    const [showAdd, setShowAdd] = useState(false)

    useEffect(() => {
        void loadData().catch(showApiError)
    }, [])

    const loadData = async () => {
        const res = await getServicesApi()
        setServices(res.map(el => ({
            id: el.id,
            name: el.server,
            ftUrl: el.sft_endpoint
        })))
    }

    const addItem = (name, ftUrl) => {
        addServiceApi(name, ftUrl).then(data => {
            setServices([...services, {
                id: data.id,
                name,
                ftUrl
            }])
            setShowAdd(false)
        }).catch(showApiError)
    }

    const handleDel = (id) => {
        deleteServiceApi(id).then(res =>
            setServices(services.filter(el => el.id !== id))
        ).catch(showApiError)
    }

    const create = () => {
        onChange()
        setShowAdd(false)
    }

    return {
        services,
        showAdd,
        addItem,
        handleDel,
        create,
        setShowAdd
    }
}
