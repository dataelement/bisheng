import AceEditor from "react-ace";

import { Button } from "../../components/bs-ui/button";
import { Label } from "../../components/bs-ui/label";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow
} from "../../components/bs-ui/table";
import {
    Tabs,
    TabsContent,
    TabsList,
    TabsTrigger,
} from "../../components/ui/tabs";

import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { useContext, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { alertContext } from "../../contexts/alertContext";
import { locationContext } from "../../contexts/locationContext";
import { userContext } from "../../contexts/userContext";
import { serverListApi, switchOnLineApi, updateConfigApi } from "../../controllers/API";
import { captureAndAlertRequestErrorHoc } from "../../controllers/request";
import { useCopyText } from "../../util/hook";
import RTConfig from "./components/RTConfig";
import { CpuDetail } from "./cpuInfo";
import { Finetune } from "./finetune";

enum STATUS {
    ONLINE,
    OFFLINE,
    ERROR,
    WAIT_ONLINE,
    WAIT_OFFLINE
}

function ConfigModal({ data, readonly, open, setOpen, onSave }) {
    const { t } = useTranslation()
    const navigate = useNavigate()

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

    return <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-[800px]">
            <DialogHeader>
                <DialogTitle>{t('model.modelConfiguration')}</DialogTitle>
            </DialogHeader>
            <div className="flex flex-wrap justify-center overflow-y-auto no-scrollbar">
                <div className="grid gap-4 py-4 mt-2 w-full">
                    <div className="grid grid-cols-8 items-center">
                        <Label htmlFor="name" className="text-left">{t('model.modelName')}</Label>
                        <p className=" text-sm text-gray-500 col-span-7 text-left ml-4">{data.model}</p>
                    </div>
                    <div className="grid grid-cols-8 items-center gap-4 mt-4">
                        <Label htmlFor="desc" className="text-left self-start col-span-8">{t('model.modelConfigLabel')}</Label>
                        <div className="col-span-8">
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
                    <div className="flex justify-start">
                        <Button variant='link' onClick={() => window.open('/model/doc')} className="link col-span-8 pl-0">{t('model.modelConfigExplanationLink')}</Button>
                    </div>
                </div>
            </div>
            <DialogFooter>
                {readonly ? <div className="flex justify-end gap-4"><Button variant='outline' type="submit" className="mt-6 h-8 rounded-full px-8" onClick={() => setOpen(false)}>{t('close')}</Button></div>
                    : <div className="flex justify-end gap-4">
                        <Button variant='outline' type="submit" className="px-11" onClick={() => setOpen(false)}>{t('cancel')}</Button>
                        <Button type="submit" className="px-11" onClick={handleCreate}>{t('confirmButton')}</Button>
                    </div>
                }
            </DialogFooter>
        </DialogContent>
    </Dialog>
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
            <div className="flex items-center text-[#00b58d]"><div className="w-2 h-2 bg-[#00b58d] mr-2 mt-[1px]"></div><span>{t('model.onlineStatus')}</span></div>,
            <div className="flex items-center text-[#aeb7d3]"><div className="w-2 h-2 bg-[#aeb7d3] mr-2 mt-[1px]"></div><span>{t('model.offlineStatus')}</span></div>,
            <div className="flex items-center text-[#ff7b2a]">
                <div className="w-2 h-2 bg-[#ff7b2a] mr-2 mt-[1px]"></div>
                <span>{t('model.exceptionStatus')}</span>
                <div className="tooltip before:break-words" data-tip={reason || t('model.warningTooltip')}><span className="flex ml-[7px] mt-1 items-center justify-center w-[15px] h-[15px] rounded-full bg-[#aeb7d3] text-[#fff] text-[12px] font-bold">?</span></div>
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
            captureAndAlertRequestErrorHoc(switchOnLineApi(el.id, true))
        } else if (el.status === STATUS.ONLINE) {
            bsConfirm({
                desc: t('model.confirmModelOffline'),
                okTxt: t('model.confirmOfflineButtonText'),
                onOk(next) {
                    setDataList(oldList => oldList.map(item =>
                        item.id === el.id ? { ...item, status: STATUS.WAIT_OFFLINE } : item
                    ))
                    // 接口
                    captureAndAlertRequestErrorHoc(switchOnLineApi(el.id, false))
                    next()
                }
            })
        }
    }

    // 保存
    const handleSave = (id, code) => {
        captureAndAlertRequestErrorHoc(updateConfigApi(id, code).then(res => {
            setOpen(false)
            setDataList(oldList => oldList.map(item =>
                item.id === id ? { ...item, config: code } : item
            ))
        }))
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

    const [showCpu, setShowCpu] = useState({
        type: 'model',
        show: false
    })

    // RT 
    const [rtOpen, setRTOpen] = useState(false)
    const handleRTChange = (change: boolean) => {
        if (change) loadData()
        setRTOpen(false)
    }

    const copyText = useCopyText()

    return <div id="model-scroll" className="w-full h-full px-2 py-4">
        <Tabs defaultValue="model" className="w-full mb-[40px]" onValueChange={e => e === 'model' && loadData()}>
            <TabsList className="">
                <TabsTrigger value="model" className="roundedrounded-xl">{t('model.modelManagement')}</TabsTrigger>
                <TabsTrigger value="finetune" disabled={user.role !== 'admin'}>{t('model.modelFineTune')}</TabsTrigger>
            </TabsList>
            <TabsContent value="model">
                <div className="relative">
                    <div className="h-[calc(100vh-136px)] overflow-y-auto pb-20">
                        <div className="flex justify-end gap-4">
                            {user.role === 'admin' && <Button variant="black" onClick={() => setShowCpu({ type: 'model', show: true })}>{t('model.gpuResourceUsage')}</Button>}
                            {user.role === 'admin' && appConfig.isDev && <Button variant="black" className="bg-[#111] hover:bg-[#48494d]" onClick={() => setRTOpen(true)}>{t('finetune.rtServiceManagement')}</Button>}
                            <Button onClick={() => { setDataList([]); loadData() }}>{t('model.refreshButton')}</Button>
                        </div>
                        <Table>
                            <TableHeader>
                                <TableRow>
                                    <TableHead className="w-[200px]">{t('model.machineName')}</TableHead>
                                    <TableHead>{t('model.modelName')}</TableHead>
                                    <TableHead>{t('model.serviceAddress')}</TableHead>
                                    <TableHead>{t('model.status')}</TableHead>
                                    <TableHead className="text-right">{t('operations')}</TableHead>
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
                                        {user.role === 'admin' ? <TableCell className="text-right">
                                            {appConfig.isDev && <Button variant="link" className={`link ${[STATUS.WAIT_ONLINE, STATUS.WAIT_OFFLINE].includes(el.status) && 'text-gray-400 cursor-default'}`}
                                                onClick={() => handleSwitchOnline(el)}>{[STATUS.ERROR, STATUS.OFFLINE, STATUS.WAIT_ONLINE].includes(el.status) ? t('model.online') : t('model.offline')}</Button>}
                                            <Button variant="link" className={`link px-0 pl-6`} onClick={() => handleOpenConfig(el)} >{t('model.modelConfiguration')}</Button> </TableCell> :
                                            <TableCell className="">--</TableCell>}
                                    </TableRow>
                                ))}
                            </TableBody>
                        </Table>
                    </div>
                    {/* 分页 */}
                    <div className="bisheng-table-footer">
                        <p className="desc">{t('model.modelCollectionCaption')}.</p>
                    </div>
                </div>
            </TabsContent>
            <TabsContent value="finetune">
                {/* 微调 */}
                <Finetune rtClick={() => setRTOpen(true)} gpuClick={() => setShowCpu({ type: 'finetune', show: true })}></Finetune>
            </TabsContent>
        </Tabs>
        {/* 编辑配置 */}
        <ConfigModal data={currentModel} readonly={readOnlyConfig || !appConfig.isDev} open={open} setOpen={setOpen} onSave={handleSave}></ConfigModal>
        {/* CPU使用情况 */}
        <Dialog open={showCpu.show} onOpenChange={(show) => setShowCpu({ ...showCpu, show })}>
            <DialogContent className="sm:max-w-[80%]">
                <DialogHeader>
                    <DialogTitle>{t('model.gpuResourceUsageTitle')}</DialogTitle>
                </DialogHeader>
                <div className="flex flex-wrap justify-center overflow-y-auto no-scrollbar">
                    {showCpu.show && <CpuDetail type={showCpu.type} />}
                </div>
            </DialogContent>
        </Dialog>
        {/* RT配置 */}
        <RTConfig open={rtOpen} onChange={handleRTChange}></RTConfig>
    </div>
};

