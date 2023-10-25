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

export default function RTConfig({ open, onChange }) {
    const nameRef = useRef(null)
    const urlRef = useRef(null)

    const { services, showAdd, addItem, handleDel, create, setShowAdd } = useRTService(onChange)

    return <dialog className={`modal bg-blur-shared ${open ? 'modal-open' : 'modal-close'}`} onClick={() => { }}>
        <div className="max-w-[800px] flex flex-col modal-box bg-[#fff] shadow-lg dark:bg-background">
            <button className="btn btn-sm btn-circle btn-ghost absolute right-2 top-2" onClick={() => onChange(false)}>✕</button>
            <h3 className="font-bold text-lg">RT服务管理</h3>
            <div className="">
                <Table className="w-full">
                    <TableHeader>
                        <TableRow>
                            <TableHead className="w-[200px]">机器名</TableHead>
                            <TableHead>服务地址</TableHead>
                            <TableHead> </TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {services.map((el) => (
                            <TableRow key={el.id}>
                                <TableCell className="py-2">{el.name}</TableCell>
                                <TableCell className="py-2">{el.url}</TableCell>
                                <TableCell className="py-2"><Button variant="ghost" className="h-8 rounded-full" onClick={() => handleDel(el.id)}>删除</Button></TableCell>
                            </TableRow>
                        ))}
                        {showAdd && <TableRow>
                            <TableCell><Input ref={nameRef} placeholder="name"></Input></TableCell>
                            <TableCell><Input ref={urlRef} placeholder="IP:PORT"></Input></TableCell>
                            <TableCell><Button variant="ghost" className="h-8 rounded-full" onClick={() => addItem(nameRef.current.value, urlRef.current.value)}>添加</Button></TableCell>
                        </TableRow>}
                    </TableBody>
                </Table>
            </div>
            <div className="flex justify-end gap-4 mt-4">
                <Button variant="ghost" className="h-8 rounded-full px-4 py-2" onClick={() => setShowAdd(true)}>加一条</Button>
                <Button type="submit" className="h-8 rounded-full px-4 py-2" onClick={create}>创建</Button>
            </div>
        </div>
    </dialog>
};

type SERVICE = {
    id: number,
    create_time?: string,
    update_time?: string,
    url: string,
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
        const { data } = await getServicesApi()
        setServices(data.data.map(el => ({
            id: el.id,
            name: el.server,
            url: el.endpoint
        })))
    }

    const addItem = async (name, url) => {
        if (!name || !url) return
        const { data } = await addServiceApi(name, url)

        setServices([...services, {
            id: data.id,
            name,
            url
        }])
        setShowAdd(false)
    }

    const handleDel = async (id) => {
        const res = await deleteServiceApi(id)
        setServices(services.filter(el => el.id !== id))
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