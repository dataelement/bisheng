import AceEditor from "react-ace";

import { Button } from "../../components/ui/button";
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
import { Link } from "react-router-dom";
import { alertContext } from "../../contexts/alertContext";
import { serverListApi, switchOnLineApi, updateConfigApi } from "../../controllers/API";
import { CpuDetail } from "./cpuInfo";
import { userContext } from "../../contexts/userContext";
import { bsconfirm } from "../../alerts/confirm";

enum STATUS {
    ONLINE,
    OFFLINE,
    ERROR,
    WAIT_ONLINE,
    WAIT_OFFLINE
}

function ConfigModal({ data, readonly, open, setOpen, onSave }) {

    const codeRef = useRef("")
    const validataRef = useRef([])

    useEffect(() => {
        if (open) codeRef.current = data.config
    }, [open])

    const { setErrorData } = useContext(alertContext);
    const handleCreate = () => {
        if (validataRef.current.length) return setErrorData({
            title: "提示: ",
            list: ['JSON格式有误']
        });

        onSave(data.id, codeRef.current)
    }

    return <dialog className={`modal bg-blur-shared ${open ? 'modal-open' : 'modal-close'}`} onClick={() => setOpen(false)}>
        <form method="dialog" className="max-w-[800px] flex flex-col modal-box bg-[#fff] shadow-lg dark:bg-background" onClick={e => e.stopPropagation()}>
            <button className="btn btn-sm btn-circle btn-ghost absolute right-2 top-2" onClick={() => setOpen(false)}>✕</button>
            <h3 className="font-bold text-lg">模型配置</h3>
            {/* <p className="py-4">知识库介绍</p> */}
            <div className="flex flex-wrap justify-center overflow-y-auto no-scrollbar">
                <div className="grid gap-4 py-4 mt-2 w-full">
                    <div className="grid grid-cols-8 items-center gap-4">
                        <Label htmlFor="name" className="text-right">模型名称</Label>
                        <p className=" text-sm text-gray-500 col-span-7">{data.model}</p>
                    </div>
                    <div className="grid grid-cols-8 items-center gap-4 mt-4">
                        <Label htmlFor="desc" className="text-right self-start">模型配置</Label>
                        <div className="col-span-7">
                            <AceEditor
                                value={data.config || '{}'}
                                mode="json"
                                theme={"twilight"}
                                highlightActiveLine={true}
                                showPrintMargin={false}
                                fontSize={14}
                                readOnly={readonly}
                                showGutter
                                enableLiveAutocompletion
                                name="CodeEditor"
                                onChange={(value) => codeRef.current = value}
                                onValidate={(e) => validataRef.current = e}
                                className="h-[500px] w-full rounded-lg border-[1px] border-border custom-scroll"
                            />
                        </div>
                    </div>
                    <div className="grid grid-cols-8 items-center gap-4">
                        <p></p>
                        <Link to={'./doc'} target="_blank" className="link col-span-7">模型配置参数说明</Link>
                    </div>
                    {readonly ? <div className="flex justify-end gap-4"><Button variant='outline' type="submit" className="mt-6 h-8 rounded-full px-8" onClick={() => setOpen(false)}>关闭</Button></div>
                        : <div className="flex justify-end gap-4">
                            <Button variant='outline' type="submit" className="mt-6 h-8 rounded-full px-8" onClick={() => setOpen(false)}>取消</Button>
                            <Button type="submit" className="mt-6 h-8 rounded-full px-8" onClick={handleCreate}>确定</Button>
                        </div>
                    }
                </div>
            </div>
        </form>
    </dialog>
}

export default function FileLibPage() {
    const [open, setOpen] = useState(false)
    const [readOnlyConfig, setReadOnlyConfig] = useState(false)
    // 
    const [datalist, setDataList] = useState([])

    const loadData = () => {
        serverListApi().then(res => {
            setDataList(res.map(item => {
                item.status = ['已上线', '未上线', '异常', '上线中', '下线中'].indexOf(item.status)
                return item
            }))
        })
    }
    useEffect(() => {
        loadData()
    }, [])
    // 当前item
    const [currentModel, setCurrentModel] = useState({})
    const handleOpenConfig = (el) => {
        setReadOnlyConfig([STATUS.ONLINE, STATUS.WAIT_ONLINE, STATUS.WAIT_OFFLINE].includes(el.status))
        setCurrentModel(el)
        setOpen(true)
    }

    // 上线状态
    const statusComponets = (status: number, reason?: string) => {
        const comps = [
            <div className="badge badge-accent"><span>已上线</span></div>,
            <div className="badge"><span>未上线</span></div>,
            <div>
                <span className="badge bg-warning" data-theme="light">异常</span>
                <div className="tooltip tooltip-warning" data-tip={reason || '处理异常'}><span data-theme="light" className="badge cursor-pointer">?</span></div>
            </div>,
            <div className="badge badge-ghost"><span>上线中</span></div>,
            <div className="badge badge-ghost"><span>下线中</span></div>,
        ]
        return comps[status]
    }

    // 点击上下线
    const handleSwitchOnline = (el) => {
        if ([STATUS.ERROR, STATUS.OFFLINE].includes(el.status)) {
            setDataList(oldList => oldList.map(item =>
                item.id === el.id ? { ...item, status: STATUS.WAIT_ONLINE } : item
            ))
            // 接口
            switchOnLineApi(el.id, true)
        } else if (el.status === STATUS.ONLINE) {
            bsconfirm({
                desc: '是否确认下线该模型，下线后使用该模型服务的技能将无法正常工作',
                okTxt: '下线',
                onOk(next) {
                    setDataList(oldList => oldList.map(item =>
                        item.id === el.id ? { ...item, status: STATUS.WAIT_OFFLINE } : item
                    ))
                    // 接口
                    switchOnLineApi(el.id, false)
                    next()
                }
            })
        }
    }

    // 保存
    const handleSave = async (id, code) => {
        const res = await updateConfigApi(id, code)

        setOpen(false)
        setDataList(oldList => oldList.map(item =>
            item.id === id ? { ...item, config: code } : item
        ))
    }

    // 5s刷新一次
    useEffect(() => {
        const timer = setTimeout(() => {
            const hasAwait = datalist.find(item => [STATUS.WAIT_OFFLINE, STATUS.WAIT_ONLINE].includes(item.status))
            hasAwait && !open && loadData()
        }, 1000 * 5);

        return () => clearTimeout(timer)
    }, [open, datalist])

    const { user } = useContext(userContext);

    const [showCpu, setShowCpu] = useState(false)
    return <div className="w-full h-screen p-6 overflow-y-auto">
        <Tabs defaultValue="account" className="w-full">
            <TabsList className="">
                <TabsTrigger value="account" className="roundedrounded-xl">模型管理</TabsTrigger>
                <TabsTrigger disabled value="password">模型Finetune</TabsTrigger>
            </TabsList>
            <TabsContent value="account">
                <div className="flex justify-end gap-4">
                    <Button className="h-8 rounded-full" onClick={() => { setDataList([]); loadData() }}>刷新</Button>
                    {user.role === 'admin' && <Button className="h-8 rounded-full" onClick={() => setShowCpu(true)}>GPU资源使用情况</Button>}
                </div>
                <Table>
                    <TableCaption>模型集合.</TableCaption>
                    <TableHeader>
                        <TableRow>
                            <TableHead className="w-[200px]">机器</TableHead>
                            <TableHead>模型名称</TableHead>
                            <TableHead>服务地址</TableHead>
                            <TableHead>状态</TableHead>
                            <TableHead>操作</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {datalist.map((el) => (
                            <TableRow key={el.id}>
                                <TableCell className="font-medium">{el.server}</TableCell>
                                <TableCell>{el.model}</TableCell>
                                <TableCell>{el.endpoint}</TableCell>
                                <TableCell>
                                    {statusComponets(el.status, el.remark)}
                                </TableCell>
                                {user.role === 'admin' ? <TableCell className="">
                                    <a href="javascript:;" className={`link ${[STATUS.WAIT_ONLINE, STATUS.WAIT_OFFLINE].includes(el.status) && 'text-gray-400 cursor-default'}`}
                                        onClick={() => handleSwitchOnline(el)}>{[STATUS.ERROR, STATUS.OFFLINE, STATUS.WAIT_ONLINE].includes(el.status) ? '上线' : '下线'}</a>
                                    <a href="javascript:;" className={`link ml-4`} onClick={() => handleOpenConfig(el)} >模型配置</a> </TableCell> :
                                    <TableCell className="">--</TableCell>}
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
                {/* 分页 */}
            </TabsContent>
            <TabsContent value="password"></TabsContent>
        </Tabs>
        {/* 编辑配置 */}
        <ConfigModal data={currentModel} readonly={readOnlyConfig} open={open} setOpen={setOpen} onSave={handleSave}></ConfigModal>
        {/* CPu使用情况 */}
        <dialog className={`modal bg-blur-shared ${showCpu ? 'modal-open' : 'modal-close'}`} onClick={() => setShowCpu(false)}>
            <form method="dialog" className="max-w-[80%] flex flex-col modal-box bg-[#fff] shadow-lg dark:bg-background" onClick={e => e.stopPropagation()}>
                <button className="btn btn-sm btn-circle btn-ghost absolute right-2 top-2" onClick={() => setShowCpu(false)}>✕</button>
                <h3 className="font-bold text-lg mb-4">GPU资源使用情况</h3>
                <div className="flex flex-wrap justify-center overflow-y-auto no-scrollbar">
                    {showCpu && <CpuDetail />}
                </div>
            </form>
        </dialog>
    </div>
};

