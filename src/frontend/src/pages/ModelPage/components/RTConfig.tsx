import { PlusCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow
} from "../../../components/ui/table";
import { addServiceApi, deleteServiceApi, getServicesApi } from "../../../controllers/API";
import { useCopyText } from "../../../util/hook";
import { useTranslation } from "react-i18next";
import { captureAndAlertRequestErrorHoc } from "../../../controllers/request";

export default function RTConfig({ open, onChange }) {

    const nameRef = useRef(null)
    const urlRef = useRef(null)
    const ftUrlRef = useRef(null)

    const { services, showAdd, addItem, handleDel, create, setShowAdd } = useRTService(onChange)

    const handleAdd = () => {
        const [name, url, ftUrl] = [nameRef.current.value, urlRef.current.value, ftUrlRef.current.value]
        if (!name || !url) return
        addItem(name, url, ftUrl)
        nameRef.current.value = ''
        urlRef.current.value = ''
        ftUrlRef.current.value = ''
    }

    const { t } = useTranslation()
    const copyText = useCopyText()

    return <dialog className={`modal bg-blur-shared ${open ? 'modal-open' : 'modal-close'}`} onClick={() => { }}>
        <div className="max-w-[820px] flex flex-col modal-box bg-[#fff] shadow-lg dark:bg-background">
            <button className="btn btn-sm btn-circle btn-ghost absolute right-2 top-2" onClick={() => onChange(false)}>✕</button>
            <h3 className="font-bold text-lg">{t('finetune.rtServiceManagement')}</h3>
            <div className="">
                <Table className="w-full">
                    <TableHeader>
                        <TableRow>
                            <TableHead className="w-[200px]">{t('model.machineName')}</TableHead>
                            <TableHead>RT{t('model.serviceAddress')}</TableHead>
                            <TableHead>FT{t('model.serviceAddress')}</TableHead>
                            <TableHead> </TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {services.map((el) => (
                            <TableRow key={el.id}>
                                <TableCell className="py-2">{el.name}</TableCell>
                                <TableCell className="py-2">
                                    <p className="cursor-pointer" onClick={e => copyText(el.url)}>{el.url}</p>
                                </TableCell>
                                <TableCell className="py-2">
                                    <p className="cursor-pointer" onClick={e => copyText(el.ftUrl)}>{el.ftUrl}</p>
                                </TableCell>
                                <TableCell className="py-2"><Button variant="ghost" className="h-8 rounded-full" onClick={() => handleDel(el.id)}>{t('delete')}</Button></TableCell>
                            </TableRow>
                        ))}
                        {showAdd && <TableRow>
                            <TableCell><Input ref={nameRef} placeholder="name"></Input></TableCell>
                            <TableCell><Input ref={urlRef} placeholder="IP:PORT"></Input></TableCell>
                            <TableCell><Input ref={ftUrlRef} placeholder="IP:PORT"></Input></TableCell>
                            <TableCell>
                                <Button variant="ghost" className="h-8 rounded-full" onClick={handleAdd}>{t('confirmButton')}</Button>
                                <Button variant="ghost" className="h-8 rounded-full text-gray-400" onClick={() => setShowAdd(false)}>{t('cancel')}</Button>
                            </TableCell>
                        </TableRow>}
                    </TableBody>
                </Table>
            </div>
            <div className="flex justify-end gap-4 mt-4">
                <Button variant="ghost" className="h-8 rounded-full" onClick={() => setShowAdd(true)}><PlusCircle className="pr-1" />{t('create')}</Button>
            </div>
        </div>
    </dialog>
};

type SERVICE = {
    id: number,
    create_time?: string,
    update_time?: string,
    url: string,
    ftUrl: string,
    remark?: string,
    name: string
}

const useRTService = (onChange) => {
    const [services, setServices] = useState<SERVICE[]>([])
    const [showAdd, setShowAdd] = useState(false)

    useEffect(() => {
        loadData()
    }, [])

    const loadData = async () => {
        const res = await getServicesApi()
        setServices(res.map(el => ({
            id: el.id,
            name: el.server,
            url: el.endpoint,
            ftUrl: el.sft_endpoint
        })))
    }

    const addItem = (name, url, ftUrl) => {
        captureAndAlertRequestErrorHoc(addServiceApi(name, url, ftUrl).then(data => {
            setServices([...services, {
                id: data.id,
                name,
                url,
                ftUrl
            }])
            setShowAdd(false)
        }))
    }

    const handleDel = (id) => {
        captureAndAlertRequestErrorHoc(deleteServiceApi(id).then(res =>
            setServices(services.filter(el => el.id !== id))
        ))
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