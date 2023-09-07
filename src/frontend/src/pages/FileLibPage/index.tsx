import { Link, useNavigate } from "react-router-dom";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import {
    Table,
    TableBody,
    TableCaption,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from "../../components/ui/table";
import {
    Tabs,
    TabsContent,
    TabsList,
    TabsTrigger,
} from "../../components/ui/tabs";

import { useContext, useEffect, useRef, useState } from "react";
import Dropdown from "../../components/dropdownComponent";
import { Textarea } from "../../components/ui/textarea";
import { alertContext } from "../../contexts/alertContext";
import { createFileLib, deleteFileLib, getEmbeddingModel, readFileLibDatabase } from "../../controllers/API";

function CreateModal({ datalist, open, setOpen }) {

    const navigate = useNavigate()

    const nameRef = useRef(null)
    const descRef = useRef(null)
    const [modal, setModal] = useState('')
    const [options, setOptions] = useState([])
    // 模型 s
    useEffect(() => {
        getEmbeddingModel().then(res => {
            const models = res.data.data.models || []
            setOptions(models)
            setModal(models[0] || '')
        })
    }, [])

    const { setErrorData } = useContext(alertContext);

    const [error, setError] = useState({ name: false, desc: false })
    const handleCreate = () => {
        const name = nameRef.current.value
        const desc = descRef.current.value
        const errorlist = []
        if (!name) errorlist.push('请填写知识库名称')
        if (name.length > 30) errorlist.push('知识库名称字数不得超过30字')
        if (!modal) errorlist.push('请选择一个模型')
        // 重名校验
        if (datalist.find(data => data.name === name)) errorlist.push('该名称已存在')
        const nameErrors = errorlist.length

        if (desc.length > 200) errorlist.push('知识库描述字数不得超过200字')
        setError({ name: !!nameErrors, desc: errorlist.length > nameErrors })
        if (errorlist.length) return handleError(errorlist)

        createFileLib({
            name,
            description: desc,
            model: modal
        }).then(res => {
            // @ts-ignore
            window.libname = name
            navigate("/files/" + res.data.id);
            setOpen(false)
        }).catch(e => {
            handleError(e.response.data.detail);
        })
    }

    const handleError = (list) => {
        // setError(msg)
        setErrorData({
            title: "提示: ",
            list
        });
    }


    return <dialog className={`modal bg-blur-shared ${open ? 'modal-open' : 'modal-close'}`} onClick={() => setOpen(false)}>
        <form method="dialog" className="max-w-[600px] flex flex-col modal-box bg-[#fff] shadow-lg dark:bg-background" onClick={e => e.stopPropagation()}>
            <button className="btn btn-sm btn-circle btn-ghost absolute right-2 top-2" onClick={() => setOpen(false)}>✕</button>
            <h3 className="font-bold text-lg">创建知识库</h3>
            {/* <p className="py-4">知识库介绍</p> */}
            <div className="flex flex-wrap justify-center overflow-y-auto no-scrollbar">
                <div className="grid gap-4 py-4 mt-2">
                    <div className="grid grid-cols-4 items-center gap-4">
                        <Label htmlFor="name" className="text-right">知识库名称</Label>
                        <Input id="name" ref={nameRef} placeholder="知识库名称" className={`col-span-3 ${error.name && 'border-red-400'}`} />
                    </div>
                    <div className="grid grid-cols-4 items-center gap-4">
                        <Label htmlFor="desc" className="text-right">描述</Label>
                        <Textarea id="desc" ref={descRef} placeholder="描述" className={`col-span-3 ${error.desc && 'border-red-400'}`} />
                    </div>
                    {options.length && <div className="grid grid-cols-4 items-center gap-4">
                        <Label className="text-right">模型</Label>
                        <Dropdown
                            options={options}
                            onSelect={(val) => setModal(val)}
                            value={modal}
                        ></Dropdown>
                    </div>}
                    <Button type="submit" className="mt-6 h-8 rounded-full" onClick={handleCreate}>创建</Button>
                </div>
            </div>
        </form>
    </dialog>
}

export default function FileLibPage() {
    const [open, setOpen] = useState(false)

    const [datalist, setDataList] = useState([])
    const loadData = () => {
        readFileLibDatabase().then(res => {
            setDataList(res)
        })
    }
    useEffect(() => {
        loadData()
    }, [])

    // 删除
    const { delShow, idRef, close, delConfim } = useDelete()

    const handleDelete = () => {
        deleteFileLib(idRef.current.id).then(res => {
            loadData()
            close()
        })
    }

    return <div className="w-full h-screen p-6 overflow-y-auto">
        <Tabs defaultValue="account" className="w-full">
            <TabsList className="">
                <TabsTrigger value="account" className="roundedrounded-xl">文件数据</TabsTrigger>
                <TabsTrigger disabled value="password">结构化数据</TabsTrigger>
            </TabsList>
            <TabsContent value="account">
                <div className="flex justify-end"><Button className="h-8 rounded-full" onClick={() => setOpen(true)}>创建</Button></div>
                <Table>
                    <TableCaption>知识库集合.</TableCaption>
                    <TableHeader>
                        <TableRow>
                            <TableHead className="w-[200px]">知识库名称</TableHead>
                            <TableHead>模型</TableHead>
                            <TableHead>创建时间</TableHead>
                            <TableHead>更新时间</TableHead>
                            <TableHead>创建用户</TableHead>
                            <TableHead className="text-right"></TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {datalist.map((el) => (
                            <TableRow key={el.id}>
                                <TableCell className="font-medium">{el.name}</TableCell>
                                <TableCell>{el.model || '--'}</TableCell>
                                <TableCell>{el.create_time.replace('T', ' ')}</TableCell>
                                <TableCell>{el.update_time.replace('T', ' ')}</TableCell>
                                <TableCell>{el.user_name || '--'}</TableCell>
                                <TableCell className="text-right" onClick={() => {
                                    // @ts-ignore
                                    window.libname = el.name
                                }}><Link to={`/files/${el.id}`} className="underline">详情</Link>
                                    <a href="javascript:;" onClick={() => delConfim(el)} className="underline ml-4">删除</a></TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
                {/* 分页 */}
            </TabsContent>
            <TabsContent value="password"></TabsContent>
        </Tabs>
        {/* 添加知识库 */}
        <CreateModal datalist={datalist} open={open} setOpen={setOpen}></CreateModal>
        {/* 删除确认 */}
        <dialog className={`modal ${delShow && 'modal-open'}`}>
            <form method="dialog" className="modal-box w-[360px] bg-[#fff] shadow-lg dark:bg-background">
                <h3 className="font-bold text-lg">提示!</h3>
                <p className="py-4">确认删除该知识库？</p>
                <div className="modal-action">
                    <Button className="h-8 rounded-full" variant="outline" onClick={close}>取消</Button>
                    <Button className="h-8 rounded-full" variant="destructive" onClick={handleDelete}>删除</Button>
                </div>
            </form>
        </dialog>
    </div>
};


const useDelete = () => {
    const [delShow, setDelShow] = useState(false)
    const idRef = useRef<any>(null)

    return {
        delShow,
        idRef,
        close: () => {
            setDelShow(false)
        },
        delConfim: (id) => {
            idRef.current = id
            setDelShow(true)
        }
    }
}