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
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { bsconfirm } from "../../alerts/confirm";
import { alertContext } from "../../contexts/alertContext";
import { locationContext } from "../../contexts/locationContext";
import { userContext } from "../../contexts/userContext";
import { serverListApi, switchOnLineApi, updateConfigApi } from "../../controllers/API";
import { useCopyText } from "../../util/hook";
import RTConfig from "./components/RTConfig";
import { CpuDetail } from "./cpuInfo";

enum STATUS {
    ONLINE,
    OFFLINE,
    ERROR,
    WAIT_ONLINE,
    WAIT_OFFLINE
}

function ConfigModal({ data, readonly, open, setOpen, onSave }) {
    const { t } = useTranslation()

    const codeRef = useRef("")
    const validataRef = useRef([])

    useEffect(() => {
        if (open) codeRef.current = data.config
    }, [open])

    const { setErrorData } = useContext(alertContext);
    const handleCreate = () => {
        if (validataRef.current.length) return setErrorData({
            title: `${t('prompt')}:`,
            list: [t('model.jsonFormatError')]
        });

        onSave(data.id, codeRef.current)
    }

    return <dialog className={`modal bg-blur-shared ${open ? 'modal-open' : 'modal-close'}`} onClick={() => setOpen(false)}>
        <form method="dialog" className="max-w-[800px] flex flex-col modal-box bg-[#fff] shadow-lg dark:bg-background" onClick={e => e.stopPropagation()}>
            <button className="btn btn-sm btn-circle btn-ghost absolute right-2 top-2" onClick={() => setOpen(false)}>✕</button>
            <h3 className="font-bold text-lg">{t('model.modelConfiguration')}</h3>
            <div className="flex flex-wrap justify-center overflow-y-auto no-scrollbar">
                <div className="grid gap-4 py-4 mt-2 w-full">
                    <div className="grid grid-cols-8 items-center gap-4">
                        <Label htmlFor="name" className="text-right">{t('model.modelName')}</Label>
                        <p className=" text-sm text-gray-500 col-span-7">{data.model}</p>
                    </div>
                    <div className="grid grid-cols-8 items-center gap-4 mt-4">
                        <Label htmlFor="desc" className="text-right self-start">{t('model.modelConfigLabel')}</Label>
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
                        <Link to={'./doc'} target="_blank" className="link col-span-7">{t('model.modelConfigExplanationLink')}</Link>
                    </div>
                    {readonly ? <div className="flex justify-end gap-4"><Button variant='outline' type="submit" className="mt-6 h-8 rounded-full px-8" onClick={() => setOpen(false)}>{t('close')}</Button></div>
                        : <div className="flex justify-end gap-4">
                            <Button variant='outline' type="submit" className="mt-6 h-8 rounded-full px-8" onClick={() => setOpen(false)}>{t('cancel')}</Button>
                            <Button type="submit" className="mt-6 h-8 rounded-full px-8" onClick={handleCreate}>{t('confirmButton')}</Button>
                        </div>
                    }
                </div>
            </div>
        </form>
    </dialog>
}

export default function FileLibPage() {
    const { t } = useTranslation()

    const { appConfig } = useContext(locationContext);
    const [open, setOpen] = useState(false)
    const [readOnlyConfig, setReadOnlyConfig] = useState(false)
    // 
    const [datalist, setDataList] = useState([])

    const loadData = () => {
        serverListApi().then(res => {
            setDataList(res.map(item => {
                item.status = ['已上线', '未上线', '异常', '上线中', '下线中'].indexOf(item.status);
                return item;
            }));
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
            <div className="badge badge-accent"><span>{t('model.onlineStatus')}</span></div>,
            <div className="badge"><span>{t('model.offlineStatus')}</span></div>,
            <div>
                <span className="badge bg-warning" data-theme="light">{t('model.exceptionStatus')}</span>
                <div className="tooltip tooltip-warning" data-tip={reason || t('model.warningTooltip')}><span data-theme="light" className="badge cursor-pointer">?</span></div>
            </div>,
            <div className="badge badge-ghost"><span>{t('model.inProgressOnlineStatus')}</span></div>,
            <div className="badge badge-ghost"><span>{t('model.inProgressOfflineStatus')}</span></div>
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
                desc: t('model.confirmModelOffline'),
                okTxt: t('model.confirmOfflineButtonText'),
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

    // RT 
    const [rtOpen, setRTOpen] = useState(false)
    const handleRTChange = (change: boolean) => {
        if (change) loadData()
        setRTOpen(false)
    }

    const copyText = useCopyText()

    return <div className="w-full h-screen p-6 overflow-y-auto">
        <Tabs defaultValue="account" className="w-full">
            <TabsList className="">
                <TabsTrigger value="account" className="roundedrounded-xl">{t('model.modelManagement')}</TabsTrigger>
                <TabsTrigger disabled value="password">{t('model.modelFineTune')}</TabsTrigger>
            </TabsList>
            <TabsContent value="account">
                <div className="flex justify-end gap-4">
                    <Button className="h-8 rounded-full" onClick={() => { setDataList([]); loadData() }}>{t('model.refreshButton')}</Button>
                    {user.role === 'admin' && <Button className="h-8 rounded-full" onClick={() => setShowCpu(true)}>{t('model.gpuResourceUsage')}</Button>}
                    {user.role === 'admin' && appConfig.isDev && <Button className="h-8 rounded-full" onClick={() => setRTOpen(true)}>{t('model.rtServiceManagement')}</Button>}
                </div>
                <Table>
                    <TableCaption>{t('model.modelCollectionCaption')}.</TableCaption>
                    <TableHeader>
                        <TableRow>
                            <TableHead className="w-[200px]">{t('model.machine')}</TableHead>
                            <TableHead>{t('model.modelName')}</TableHead>
                            <TableHead>{t('model.serviceAddress')}</TableHead>
                            <TableHead>{t('model.status')}</TableHead>
                            <TableHead>{t('operations')}</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {datalist.map((el) => (
                            <TableRow key={el.id}>
                                <TableCell className="font-medium">{el.server}</TableCell>
                                <TableCell>{el.model}</TableCell>
                                <TableCell>
                                    <p className="cursor-pointer" onClick={() => copyText(el.endpoint)}>{el.endpoint}</p>
                                </TableCell>
                                <TableCell>
                                    {statusComponets(el.status, el.remark)}
                                </TableCell>
                                {user.role === 'admin' ? <TableCell className="">
                                    {appConfig.isDev && <a href="javascript:;" className={`link ${[STATUS.WAIT_ONLINE, STATUS.WAIT_OFFLINE].includes(el.status) && 'text-gray-400 cursor-default'}`}
                                        onClick={() => handleSwitchOnline(el)}>{[STATUS.ERROR, STATUS.OFFLINE, STATUS.WAIT_ONLINE].includes(el.status) ? t('model.online') : t('model.offline')}</a>}
                                    <a href="javascript:;" className={`link ml-4`} onClick={() => handleOpenConfig(el)} >{t('model.modelConfiguration')}</a> </TableCell> :
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
        <ConfigModal data={currentModel} readonly={readOnlyConfig || !appConfig.isDev} open={open} setOpen={setOpen} onSave={handleSave}></ConfigModal>
        {/* CPU使用情况 */}
        <dialog className={`modal bg-blur-shared ${showCpu ? 'modal-open' : 'modal-close'}`} onClick={() => setShowCpu(false)}>
            <form method="dialog" className="max-w-[80%] flex flex-col modal-box bg-[#fff] shadow-lg dark:bg-background" onClick={e => e.stopPropagation()}>
                <button className="btn btn-sm btn-circle btn-ghost absolute right-2 top-2" onClick={() => setShowCpu(false)}>✕</button>
                <h3 className="font-bold text-lg mb-4">{t('model.gpuResourceUsageTitle')}</h3>
                <div className="flex flex-wrap justify-center overflow-y-auto no-scrollbar">
                    {showCpu && <CpuDetail />}
                </div>
            </form>
        </dialog>
        {/* RT配置 */}
        <RTConfig open={rtOpen} onChange={handleRTChange}></RTConfig>
    </div>
};

