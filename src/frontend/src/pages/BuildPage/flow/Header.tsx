import TipPng from "@/assets/tip.jpg";
import { TitleLogo } from "@/components/bs-comp/cardComponent";
import { AssistantIcon, DelIcon, LoadIcon } from "@/components/bs-icons";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Badge } from "@/components/bs-ui/badge";
import { Button } from "@/components/bs-ui/button";
import ActionButton from "@/components/bs-ui/button/actionButton";
import TextInput from "@/components/bs-ui/input/textInput";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/bs-ui/popover";
import { RadioGroup, RadioGroupItem } from "@/components/bs-ui/radio";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { TabsContext } from "@/contexts/tabsContext";
import { createFlowVersion, deleteVersion, getFlowVersions, getVersionDetails, updateVersion } from "@/controllers/API/flow";
import { onlineWorkflow, saveWorkflow } from "@/controllers/API/workflow";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { AppType } from "@/types/app";
import { FlowVersionItem } from "@/types/flow";
import { ChevronLeft, EllipsisVertical, PencilLineIcon, Play } from "lucide-react";
import { useContext, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import CreateApp from "../CreateApp";
import { ChatTest } from "./FlowChat/ChatTest";
import useFlowStore from "./flowStore";

const Header = ({ flow, onTabChange }) => {
    const { message } = useToast()
    const testRef = useRef(null)
    const updateAppModalRef = useRef(null)
    const { uploadFlow } = useFlowStore()
    const { t } = useTranslation()
    console.log('flow :>> ', flow);

    const validateNodes = useNodeEvent(flow)

    const handleRunClick = () => {
        // 记录错误日志
        const errors = validateNodes()
        if (errors.length) return message({
            description: errors,
            variant: 'warning'
        })

        testRef.current?.run(flow)
    }

    const handleOnlineClick = async () => {
        const errors = validateNodes()
        if (errors.length) return message({
            description: errors,
            variant: 'warning'
        })

        // api请求
        const res = await captureAndAlertRequestErrorHoc(onlineWorkflow(flow, 2))
        if (res) {
            message({
                variant: 'success',
                description: "上线成功"
            })
        }
    }

    const handleSaveClick = async () => {

        if (isOnlineVersion()) return message({
            title: '提示',
            description: '工作流已上线不可编辑，您可以另存为新版本进行保存',
            variant: 'warning'
        })
        // temp
        // localStorage.setItem('flow_tmp', JSON.stringify(flow))
        const res = await captureAndAlertRequestErrorHoc(saveWorkflow(version.id, {
            ...flow,
            data: {
                nodes: flow.nodes,
                edges: flow.edges,
                viewport: flow.viewport
            }
        }))
        res && message({
            variant: 'success',
            description: "保存成功"
        })
    }

    const handleExportClick = () => {
        setOpen(false)
        const jsonString = `data:text/json;chatset=utf-8,${encodeURIComponent(
            JSON.stringify({ ...flow })
        )}`;
        const link = document.createElement("a");
        link.href = jsonString;
        link.download = `${flow.name || '工作流实验数据'}.json`;

        link.click();
    }

    const handleImportClick = () => {
        setOpen(false)
        bsConfirm({
            desc: "导入将会覆盖现有工作流，确认导入？",
            onOk(next) {
                uploadFlow()
                next()
            }
        })
    }
    // versions
    const [loading, setLoading] = useState(false)
    const { flow: f, setFlow } = useFlowStore()
    const { versions, version, lastVersionIndexRef, isOnlineVersion, changeName, deleteVersion, refrenshVersions, setCurrentVersion } = useVersion(flow)
    // 切换版本
    const handleChangeVersion = async (versionId) => {
        setLoading(true)
        // 切换版本UI
        setCurrentVersion(Number(versionId))
        // 加载选中版本data
        const res = await getVersionDetails(versionId)
        console.log('res :>> ', res)
        // 自动触发 page的 clone flow
        setFlow({ ...f, ...res.data })
        message({
            variant: "success",
            title: `切换到 ${res.name}`,
            description: ""
        })
        setLoading(false)
    }
    const [saveVersionId, setVersionId] = useState('')
    useEffect(() => {
        saveVersionId && handleChangeVersion(saveVersionId)
    }, [saveVersionId])
    // new version
    const handleSaveNewVersion = async () => {
        // 累加版本 vx ++
        const maxNo = lastVersionIndexRef.current + 1
        const { nodes, edges, viewport } = flow
        const res = await captureAndAlertRequestErrorHoc(
            createFlowVersion(flow.id, { name: `v${maxNo}`, description: '', data: { nodes, edges, viewport }, original_version_id: version.id })
        )
        message({
            variant: "success",
            title: `${t('skills.version')} v${maxNo} ${t('skills.saveSuccessful')}`,
            description: ""
        })
        // 更新版本列表
        await refrenshVersions()
        // 切换到最新版本

        setVersionId(res.id)
    }

    const [tabType, setTabType] = useState('edit')
    const [open, setOpen] = useState(false)
    return (
        <header className="flex justify-between items-center p-4 py-2 bisheng-bg border-b">
            {
                loading && <div className=" fixed left-0 top-0 w-full h-screen bg-background/60 z-50 flex items-center justify-center">
                    <LoadIcon className="mr-2 text-gray-600" />
                    <span>切换到 {version.name}</span>
                </div>
            }
            {/* Left Section with Back Button and Title */}
            <div className="flex items-center">
                <Button variant="outline" size="icon" className="bg-[#fff] size-8"
                    onClick={() => {
                        window.history.back()
                    }}
                ><ChevronLeft /></Button>
                <div className="flex items-center ml-5">
                    <TitleLogo
                        url={flow.logo}
                        id={2}
                        className=""
                    ><AssistantIcon /></TitleLogo>
                    <div className="pl-3">
                        <h1 className="font-medium text-sm flex gap-2">
                            <span className="truncate max-w-48 font-bold">{flow.name}</span>
                            <Button
                                size="icon"
                                variant="ghost"
                                className="size-6"
                                onClick={() => updateAppModalRef.current?.edit(AppType.FLOW, flow)}>
                                <PencilLineIcon className="size-4 text-gray-500"></PencilLineIcon>
                            </Button>
                        </h1>
                        <p className="text-xs text-gray-500 mt-0.5">
                            <Badge variant="gray" className="font-light">当前版本: {version?.name}</Badge>
                        </p>
                    </div>
                </div>
            </div>
            <div>
                <Button variant="secondary" className={`${tabType === 'edit' ? 'bg-[#fff] hover:bg-[#fff]/70 text-primary h-8"' : ''} h-8`}
                    onClick={() => { setTabType('edit'); onTabChange('edit') }}
                >
                    流程编排
                </Button>
                <Button variant="secondary" className={`${tabType === 'api' ? 'bg-[#fff] hover:bg-[#fff]/70 text-primary h-8"' : ''} h-8`}
                    onClick={() => { setTabType('api'); onTabChange('api') }}>
                    对外发布
                </Button>
            </div>
            {/* Right Section with Options */}
            <div className="flex items-center gap-3">
                {/* <Button size="icon" variant="outline" disabled className="bg-[#fff] h-8">
                    <Bell size={16} />
                </Button> */}
                <Button variant="outline" size="sm" className="bg-[#fff] h-8" onClick={handleRunClick}>
                    <Play className="size-3.5 mr-1" />
                    运行
                </Button>
                <Button variant="outline" size="sm" className="bg-[#fff] h-8 px-6" onClick={handleSaveClick}>
                    保存
                </Button>
                {
                    version && <ActionButton
                        size="sm"
                        className="px-6 flex gap-2 bg-[#fff]"
                        iconClassName="bg-[#fff]"
                        align="end"
                        variant="outline"
                        onClick={handleSaveNewVersion}
                        delayDuration={200}
                        buttonTipContent={(
                            <div>
                                <img src={TipPng} alt="" className="w-80" />
                                <p className="mt-4 text-sm">{t('skills.supportVersions')}</p>
                            </div>
                        )}
                        dropDown={(
                            <div className=" overflow-y-auto max-h-96 max-h">
                                <RadioGroup value={version.id + ''} onValueChange={(vid) => {
                                    updateVersion(version.id, { name: version.name, description: '', data: flow.data })
                                    handleChangeVersion(vid)
                                }} className="gap-0">
                                    {versions.map((vers, index) => (
                                        <div key={vers.id} className="group flex items-center gap-4 px-4 py-2 cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700 border-b">
                                            <RadioGroupItem value={vers.id + ''} />
                                            <div className="w-[198px]">
                                                <TextInput
                                                    className="h-[30px]"
                                                    type="hover"
                                                    value={vers.name}
                                                    maxLength={30}
                                                    onSave={val => changeName(vers.id, val)}
                                                ></TextInput>
                                                <p className="text-sm text-muted-foreground mt-2">{vers.update_time.replace('T', ' ').substring(0, 16)}</p>
                                            </div>
                                            {
                                                // 最后一个 V0 版本和当前选中版本不允许删除
                                                !(version.id === vers.id)
                                                && <Button
                                                    className="group-hover:flex hidden"
                                                    type="button"
                                                    size="icon"
                                                    variant="outline"
                                                    onClick={() => deleteVersion(vers, index)}
                                                ><DelIcon /></Button>
                                            }
                                        </div>
                                    ))}
                                </RadioGroup>
                            </div>
                        )}
                    >{t('skills.saveVersion')}</ActionButton>
                }
                <Button size="sm" className="h-8 px-6" onClick={handleOnlineClick}>
                    上线
                </Button>
                <Popover open={open} onOpenChange={setOpen}>
                    <PopoverTrigger asChild >
                        <Button size="icon" variant="outline" className="bg-[#fff] size-8">
                            <EllipsisVertical size={16} />
                        </Button>
                    </PopoverTrigger>
                    <PopoverContent className="w-auto p-2 cursor-pointer">
                        <div
                            className="rounded-sm py-1.5 pl-2 pr-8 text-sm hover:bg-[#EBF0FF] dark:text-gray-50 dark:hover:bg-gray-700"
                            onClick={handleImportClick}>导入工作流</div>
                        <div
                            className="rounded-sm py-1.5 pl-2 pr-8 text-sm hover:bg-[#EBF0FF] dark:text-gray-50 dark:hover:bg-gray-700"
                            onClick={handleExportClick}>导出工作流</div>
                    </PopoverContent>
                </Popover>
            </div>
            <ChatTest ref={testRef} />
            {/* 修改应用弹窗 flow&assistant */}
            <CreateApp ref={updateAppModalRef} onSave={(base) => {
                f.name = base.name
                f.description = base.description
                f.logo = base.logo
                setFlow({ ...f, ...base })
                onlineWorkflow(f)
            }} />
        </header>
    );
};

/** 收集节点事件
 * return validate<func>
 * */
const useNodeEvent = (flow) => {
    // 收集节点校验事件(表单 变量)
    const nodeValidateEntitiesRef = useRef({})
    useEffect(() => {
        const setNodeEvent = (e) => {
            const { action, id } = e.detail
            if (action === 'update') {
                nodeValidateEntitiesRef.current[id] = e.detail.validate
            } else {
                delete nodeValidateEntitiesRef.current[id]
            }
        }
        window.addEventListener('node_event', setNodeEvent)
        return () => {
            window.removeEventListener('node_event', setNodeEvent)
        }
    }, [])

    return () => {
        let errors = []
        Object.keys(nodeValidateEntitiesRef.current).forEach(key => {
            errors = [...errors, ...nodeValidateEntitiesRef.current[key]()]
        })

        if (errors.length) return errors

        /**
         * branch flows
         * 梳理每条分支线 验证连线逻辑
         */
        const branchLines: { branch: string, nodeIds: { branch: string, nodeId: string }[], end: boolean }[] = []
        const nodeMap = {}
        const startNodeId = flow.edges.find(node => node.source.indexOf('start') === 0).source
        const findEdgesByNodeId = (id) => {
            return flow.edges.filter(node => node.source === id)
        }

        const traverseTree = (nodeId, branchId, nodeIds) => {
            const edges = findEdgesByNodeId(nodeId)
            edges.forEach((edge, index) => {
                const [source, target] = [edge.source.split('_')[0], edge.target.split('_')[0]]
                const _branchId = `${branchId}_${index}`
                const _nodeIds = [...nodeIds, { branch: _branchId, nodeId: edge.target }]

                if (target === 'end') {
                    // stop when loop or end 
                    branchLines.push({ branch: _branchId, nodeIds: _nodeIds, end: true })
                } else if (nodeMap[edge.target]) {
                    // stop when loop or end 
                    branchLines.push({ branch: branchId, nodeIds, end: true })
                } else {
                    nodeMap[edge.target] = true
                    traverseTree(edge.target, _branchId, _nodeIds)
                }
            })

            if (edges.length === 0) {
                branchLines.push({ branch: branchId, nodeIds, end: false })
            }
        }

        traverseTree(startNodeId, '0', [{ branch: '0', nodeId: startNodeId }])
        // console.log('flow :>> ', flow.edges, branchLines);

        // event func
        const sendEvent = (ids) => {
            const event = new CustomEvent('nodeErrorBorderEvent', {
                detail: {
                    nodeIds: ids
                }
            })
            window.dispatchEvent(event)
        }

        // 并行校验
        const [inputParallelNids, outputParallelNids] = branchLines.reduce(
            ([inputNodes, outputNodes], line) => {
                ['input', 'output'].forEach((type, index) => {
                    const nodeId = line.nodeIds.find(node => node.nodeId.startsWith(type));
                    if (nodeId && ![inputNodes, outputNodes][index].some(el => el.branch === nodeId.branch)) {
                        [inputNodes, outputNodes][index].push(nodeId);
                    }
                });
                return [inputNodes, outputNodes];
            },
            [[], []]
        );

        if (inputParallelNids.length > 1 || outputParallelNids.length > 1) {
            sendEvent([
                ...inputParallelNids.length > 1 ? inputParallelNids.map(node => node.nodeId) : [],
                ...outputParallelNids.length > 1 ? outputParallelNids.map(node => node.nodeId) : []
            ])
            return ['不支持多个 input 节点或 output 节点（输入型交互）并行执行']
        }

        // 开始到结束流程是否完整
        const errorLine = branchLines.find(line => !line.end)
        if (errorLine) {
            sendEvent([errorLine.nodeIds[errorLine.nodeIds.length - 1].nodeId])
            return ['缺少结束节点']
        }

        sendEvent([]) // reduction
        return errors
    }
}



// 技能版本管理
const useVersion = (flow) => {
    const { t } = useTranslation()
    const [versions, setVersions] = useState<FlowVersionItem[]>([])
    const { version, setVersion } = useContext(TabsContext)
    // 上线版本的版本 id
    const [onlineVid, setOnlineVid] = useState(0);
    const updateOnlineVid = (vid: number) => {
        setOnlineVid(flow.status === 2 ? vid : 0);
    }
    const lastVersionIndexRef = useRef(0)

    const refrenshVersions = () => {
        return getFlowVersions(flow.id).then(({ data, total }) => {
            setVersions(data)
            lastVersionIndexRef.current = total - 1
            const currentV = data.find(el => el.is_current === 1)
            setVersion(currentV)
            // 记录上线的版本
            updateOnlineVid(currentV?.id)
        })
    }

    useEffect(() => {
        refrenshVersions()
    }, [])

    // 修改名字
    const handleChangName = (id, name) => {
        captureAndAlertRequestErrorHoc(updateVersion(id, { name, description: '', data: null }))
        // 乐观更新
        setVersions(versions.map(version => {
            if (version.id === id) {
                version.name = name;
            }
            return version;
        }))
    }

    const handleDeleteVersion = (version, index) => {
        bsConfirm({
            title: t('prompt'),
            desc: `${t('skills.deleteOrNot')} ${version.name} ${t('skills.version')}?`,
            onOk: (next) => {
                captureAndAlertRequestErrorHoc(deleteVersion(version.id)).then(res => {
                    if (res === null) {
                        // 乐观更新
                        setVersions(versions.filter((_, i) => i !== index))
                    }
                })
                next()
            }
        })
    }

    return {
        versions,
        version,
        isOnlineVersion: () => version.id === onlineVid,
        lastVersionIndexRef,
        setCurrentVersion(versionId) {
            const currentV = versions.find(el => el.id === versionId)
            setVersion(currentV)
            return currentV
        },
        refrenshVersions,
        deleteVersion: handleDeleteVersion,
        changeName: handleChangName,
    }
}


export default Header;
