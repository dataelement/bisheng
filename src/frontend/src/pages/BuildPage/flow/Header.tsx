import TipPng from "@/assets/tip.jpg";
import { TitleLogo } from "@/components/bs-comp/cardComponent";
import { AssistantIcon, DelIcon, LoadIcon } from "@/components/bs-icons";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Badge } from "@/components/bs-ui/badge";
import { Button } from "@/components/bs-ui/button";
import ActionButton from "@/components/bs-ui/button/actionButton";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import TextInput from "@/components/bs-ui/input/textInput";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/bs-ui/popover";
import { RadioGroup, RadioGroupItem } from "@/components/bs-ui/radio";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { darkContext } from "@/contexts/darkContext";
import { TabsContext } from "@/contexts/tabsContext";
import { createFlowVersion, deleteVersion, getFlowVersions, getVersionDetails, updateVersion } from "@/controllers/API/flow";
import { onlineWorkflow, onlineWorkflowApi, saveWorkflow } from "@/controllers/API/workflow";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { AppType } from "@/types/app";
import { FlowVersionItem } from "@/types/flow";
import { findParallelNodes } from "@/util/flowUtils";
import { isEqual } from "lodash-es";
import { ChevronLeft, EllipsisVertical, PencilLineIcon, Play, ShieldCheck } from "lucide-react";
import { useContext, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { unstable_useBlocker as useBlocker, useNavigate } from "react-router-dom";
import CreateApp from "../CreateApp";
import { ChatTest } from "./FlowChat/ChatTest";
import useFlowStore from "./flowStore";
import Notification from "./Notification";

const Header = ({ flow, onTabChange, preFlow, onChange }) => {
    const { message } = useToast()
    const { dark } = useContext(darkContext);
    const testRef = useRef(null)
    const updateAppModalRef = useRef(null)
    const { uploadFlow } = useFlowStore()
    const { t, i18n } = useTranslation('flow')
    const navigate = useNavigate()
    const [modelVersionId, setModelVersionId] = useState(0)

    // console.log('flow :>> ', flow);

    const validateNodes = useNodeEvent(flow)
    const addNotification = useFlowStore((state) => state.addNotification);

    const handleRunClick = () => {
        // 记录错误日志
        const errors = validateNodes()
        if (errors.length) {
            errors.map(el => addNotification({
                type: 'warning',
                title: '',
                description: el
            }))
            return message({
                description: errors,
                variant: 'warning'
            })
        }

        testRef.current?.run(flow)
    }

    const handleOnlineClick = async () => {
        const errors = validateNodes()
        if (errors.length) {
            errors.map(el => addNotification({
                type: 'warning',
                title: '',
                description: el
            }))
            return message({
                description: errors,
                variant: 'warning'
            })
        }

        await captureAndAlertRequestErrorHoc(saveWorkflow(version.id, {
            ...flow,
            name: version.name,
            data: {
                nodes: flow.nodes,
                edges: flow.edges,
                viewport: flow.viewport
            }
        }))
        setFlow({ ...flow })
        // api请求
        const res = await captureAndAlertRequestErrorHoc(onlineWorkflowApi({ flow_id: flow.id, version_id: version.id, status: 2 }))
        if (res === null) {
            message({
                variant: 'success',
                description: `${version?.name} ${t('hasBeenLaunched')}`
            })
            window.history.length > 1 ? window.history.back() : navigate('/build/apps')
        }
    }
    const handleOfflineClick = async () => {
        const res = await captureAndAlertRequestErrorHoc(onlineWorkflowApi({ flow_id: flow.id, version_id: version.id, status: 1 }))
        if (res === null) {
            message({
                variant: 'success',
                description: `${version?.name} ${t('hasBeenOffline')}`
            })

            flow.status = 1
            refrenshVersions()
        }
    }

    const handleSaveClick = async () => {

        if (isOnlineVersionFun()) {
            message({
                description: t('currentVersionLaunched'),
                variant: 'warning'
            })
            return !hasChanged
        }
        // temp
        // localStorage.setItem('flow_tmp', JSON.stringify(flow))
        const res = await captureAndAlertRequestErrorHoc(saveWorkflow(version.id, {
            ...flow,
            name: version.name,
            data: {
                nodes: flow.nodes,
                edges: flow.edges,
                viewport: flow.viewport
            }
        }))
        res && message({
            variant: 'success',
            description: t('changesSaved')
        })
        setFlow({ ...flow })
        return res
    }

    const handleExportClick = () => {
        setOpen(false)
        const jsonString = `data:text/json;chatset=utf-8,${encodeURIComponent(
            JSON.stringify({ ...flow })
        )}`;
        const link = document.createElement("a");
        link.href = jsonString;
        link.download = `${flow.name || t('defaultWorkflowData')}.json`

        link.click();
    }

    const handleImportClick = () => {
        setOpen(false)
        bsConfirm({
            desc: t('confirmImport'),
            onOk(next) {
                uploadFlow()
                next()
            }
        })
    }
    // versions
    const [loading, setLoading] = useState(false)
    const { flow: f, setFlow, setFitView } = useFlowStore()
    const { versions, version, lastVersionIndexRef, isOnlineVersion, isOnlineVersionFun, changeName, deleteVersion, refrenshVersions, setCurrentVersion } = useVersion(flow)
    // 切换版本
    const handleChangeVersion = async (versionId) => {
        setLoading(true)
        // 切换版本UI
        window.flow_version = Number(versionId)
        // 加载选中版本data
        const res = await getVersionDetails(versionId)
        // console.log('res :>> ', res)
        // 自动触发 page的 clone flow
        setFlow(null)
        setTimeout(() => {
            setFlow({ ...f, ...res.data })
        }, 0);
        // message({
        //     variant: "success",
        //     title: t('switchToVersion', { versionName: res.name }),
        //     description: ""
        // })
        setLoading(false)
        setFitView()
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
            title: `${t('skills.version', {ns: 'bs'})} v${maxNo} ${t('skills.saveSuccessful', {ns: 'bs'})}`,
            description: ""
        })
        // 更新版本列表
        await refrenshVersions()
        // 切换到最新版本

        setVersionId(res.id)
    }

    const [tabType, setTabType] = useState('edit')
    const [open, setOpen] = useState(false)

    const [blocker, hasChanged] = useBeforeUnload(flow, preFlow)
    // 离开并保存
    const handleSaveAndClose = async () => {
        if (isOnlineVersion) {
            handleSaveNewVersion()
            blocker.reset?.()
        } else {
            const res = await handleSaveClick()
            res ? blocker.proceed?.() : blocker.reset?.()
        }
    }

    return (
        <header className="flex justify-between items-center p-4 py-2 bisheng-bg border-b">
            {
                loading && <div className=" fixed left-0 top-0 w-full h-screen bg-background/60 z-50 flex items-center justify-center">
                    <LoadIcon className="mr-2 text-gray-600" />
                    <span>{t('switchToVersion', { versionName: version.name })}</span>
                </div>
            }
            {/* Left Section with Back Button and Title */}
            <div className="flex items-center">
                <Button variant="outline" size="icon" className={`${!dark && 'bg-[#fff]'} size-8`}
                    onClick={() => {
                        window.history.length > 1 ? window.history.back() : navigate('/build/apps')
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
                            <Badge variant="gray" className="font-light dark:bg-gray-950 dark:text-gray-400"><ShieldCheck size={14} />{t('currentVersion', { versionName: version?.name })}</Badge>
                        </p>
                    </div>
                </div>
            </div>
            <div>
                <Button variant="secondary" className={`${tabType === 'edit' ? 'bg-[#fff] dark:bg-gray-950 hover:bg-[#fff]/70 text-primary h-8"' : ''} h-8`}
                    onClick={() => { setTabType('edit'); onTabChange('edit') }}
                >
                    {t('processOrchestration')}
                </Button>
                <Button variant="secondary" className={`${tabType === 'api' ? 'bg-[#fff] dark:bg-gray-950 hover:bg-[#fff]/70 text-primary h-8"' : ''} h-8`}
                    onClick={() => { setTabType('api'); onTabChange('api') }}>
                    {t('externalRelease')}
                </Button>
            </div>
            {/* Right Section with Options */}
            <div className="flex items-center gap-3">
                <Notification />
                <Button variant="outline" size="sm" className={`${!dark && 'bg-[#fff]'} h-8`} onClick={handleRunClick}>
                    <Play className="size-3.5 mr-1" />
                    {t('run')}
                </Button>
                <Button variant="outline" size="sm" className={`${!dark && 'bg-[#fff]'} h-8 px-6`} onClick={handleSaveClick}>
                    {t('save')}
                </Button>
                {
                    version && <ActionButton
                        size="sm"
                        className={`px-6 flex gap-2 ${!dark && 'bg-[#fff]'}`}
                        iconClassName={`${!dark && 'bg-[#fff]'}`}
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
                                    if (isOnlineVersionFun() && hasChanged) return setModelVersionId(vid)
                                    const { edges, nodes, viewport } = flow
                                    updateVersion(version.id, {
                                        name: version.name, description: '', data: {
                                            edges, nodes, viewport
                                        }
                                    })
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
                                                    onSave={val => changeName(vers.id, val || vers.name)}
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
                    >{t('skills.saveVersion', { ns: 'bs' })}</ActionButton>
                }
                {isOnlineVersion ? <Button size="sm" className={`h-8 px-6`} onClick={handleOfflineClick}>
                    {t('takeOffline')}
                </Button> : <Button size="sm" className={`h-8 px-6`} onClick={handleOnlineClick}>
                    {t('goOnline')}
                </Button>}
                <Popover open={open} onOpenChange={setOpen}>
                    <PopoverTrigger asChild >
                        <Button size="icon" variant="outline" className={`${!dark && 'bg-[#fff]'} size-8`}>
                            <EllipsisVertical size={16} />
                        </Button>
                    </PopoverTrigger>
                    <PopoverContent className="w-auto p-2 cursor-pointer">
                        <div
                            className="rounded-sm py-1.5 pl-2 pr-8 text-sm hover:bg-[#EBF0FF] dark:text-gray-50 dark:hover:bg-gray-700"
                            onClick={handleImportClick}>{t('importWorkflow')}</div>
                        <div
                            className="rounded-sm py-1.5 pl-2 pr-8 text-sm hover:bg-[#EBF0FF] dark:text-gray-50 dark:hover:bg-gray-700"
                            onClick={handleExportClick}> {t('exportWorkflow')}</div>
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
            {/* 上线不可修改提示 */}
            <Dialog open={!!modelVersionId}>
                <DialogContent className="sm:max-w-[425px]" close={false}>
                    <DialogHeader>
                        <DialogTitle>{t('prompt')}</DialogTitle>
                        <DialogDescription>{t('currentVersionLaunched')}</DialogDescription>
                    </DialogHeader>
                    <DialogFooter className="mt-4">
                        <Button className="h-8" onClick={() => {
                            handleSaveNewVersion()
                            setModelVersionId(0)
                        }}>
                            {t('saveAsNewVersion')}
                        </Button>
                        <Button className="leave h-8" variant="destructive" onClick={() => {
                            handleChangeVersion(modelVersionId)
                            setModelVersionId(0)
                        }}>
                            {t('dontSaveAndSwitch')}
                        </Button>
                        <Button className="h-8" variant="outline" onClick={() => setModelVersionId(0)}>
                            {t('cancel')}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
            {/* 离开并保存提示 */}
            <Dialog open={blocker.state === "blocked"}>
                <DialogContent className="sm:max-w-[425px]" close={false}>
                    <DialogHeader>
                        <DialogTitle>{t('prompt')}</DialogTitle>
                        <DialogDescription>{isOnlineVersion ? '当前版本已上线,不可进行更改' : '您有未保存的更改,确定要离开吗?'}</DialogDescription>
                    </DialogHeader>
                    <DialogFooter>
                        <Button className="leave h-8" onClick={handleSaveAndClose}>
                            {isOnlineVersion ? '另存为新版本' : '离开并保存'}
                        </Button>
                        <Button className="h-8" variant="destructive" onClick={() => blocker.proceed?.()}>
                            {t('dontSave')}
                        </Button>
                        <Button className="h-8" variant="outline" onClick={() => {
                            const dom = document.getElementById("flow-page") as HTMLElement;
                            blocker.reset?.()
                            if (dom) dom.className = dom.className.replace('report-hidden', '');
                        }}>
                            {t('cancel')}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </header>
    );
};

/** 收集节点事件
 * return validate<func>
 * */
const useNodeEvent = (flow) => {
    const { t } = useTranslation('flow');
    // 收集节点校验事件(表单 变量)
    const nodeValidateEntitiesRef = useRef({});
    useEffect(() => {
        const setNodeEvent = (e) => {
            const { action, id } = e.detail;
            if (action === 'update') {
                nodeValidateEntitiesRef.current[id] = e.detail.validate;
            } else {
                delete nodeValidateEntitiesRef.current[id];
            }
        };
        window.addEventListener('node_event', setNodeEvent);
        return () => {
            window.removeEventListener('node_event', setNodeEvent);
        };
    }, []);

    return () => {
        let errors = [];
        Object.keys(nodeValidateEntitiesRef.current).forEach(key => {
            errors = [...errors, ...nodeValidateEntitiesRef.current[key]()];
        });

        // event func
        const sendEvent = (ids) => {
            const event = new CustomEvent('nodeErrorBorderEvent', {
                detail: {
                    nodeIds: ids
                }
            });
            window.dispatchEvent(event);
        };

        if (errors.length) return errors;
        if (!flow.edges.length) {
            sendEvent([flow.nodes.find(node => node.data.type === 'start').id]);
            return [t('missingEndNode')];
        }

        /**
         * branch flows
         * 梳理每条分支线 验证连线逻辑
         */
        const branchLines: { branch: string, nodeIds: { branch: string, nodeId: string }[], end: boolean }[] = [];
        const nodeMap = {};
        const treeNodeIdSet = new Set();
        const startEdge = flow.edges.find(node => node.source.indexOf('start') === 0);
        if (!startEdge) return [t('pleaseLinkStartNode')];
        const startNodeId = startEdge.source;
        const findEdgesByNodeId = (id) => {
            return flow.edges.filter(node => node.source === id);
        };
        const findOutType = (nodeId) => {
            if (!nodeId.startsWith('output')) return '';
            return flow.nodes.find(node => node.id === nodeId).data.group_params[0].params[1].value.type;
        };

        const traverseTree = (nodeId, branchId, nodeIds) => {
            const edges = findEdgesByNodeId(nodeId);
            edges.forEach((edge, index) => {
                const [source, target] = [edge.source.split('_')[0], edge.target.split('_')[0]];
                const _branchId = `${branchId}_${index}`;
                const _nodeIds = [...nodeIds, { branch: _branchId, nodeId: edge.target, type: findOutType(edge.target) }];
                treeNodeIdSet.add(edge.target);

                if (target === 'end') {
                    // stop when loop or end 
                    branchLines.push({ branch: _branchId, nodeIds: _nodeIds, end: true });
                } else if (nodeMap[edge.target]) {
                    // stop when loop or end 
                    branchLines.push({ branch: branchId, nodeIds, end: true });
                } else {
                    nodeMap[edge.target] = true;
                    traverseTree(edge.target, _branchId, _nodeIds);
                }
            });

            if (edges.length === 0) {
                branchLines.push({ branch: branchId, nodeIds, end: false });
            }
        };

        traverseTree(startNodeId, '0', [{ branch: '0', nodeId: startNodeId, type: '' }]);

        if (treeNodeIdSet.size !== flow.nodes.length - 1) {
            return [t('unconnectedNodes')];
        }
        // console.log('flow :>> ', flow.edges, branchLines);

        // 并行校验
        // input节点s & 分支节点s
        const nodeLMap = {};
        const [inputNodeLs, outputNodeLs, branchNodeLs] = branchLines.reduce(
            ([inputNodeLs, outputNodeLs, branchNodeLs], line) => {
                line.nodeIds.forEach(node => {
                    if (node.nodeId.startsWith('input')) {
                        const inputNode = flow.nodes.find(_node => _node.id === node.nodeId && _node.data.tab.value === 'input');
                        // It is an input & ouput node and is different from the branch path in ids;
                        if (inputNode && !inputNodeLs.some(el => el.branch === inputNode.branch)) {
                            !nodeLMap[node.branch] && inputNodeLs.push(node);
                        }
                    } else if (node.nodeId.startsWith('output') && node.type === 'input') {
                        !nodeLMap[node.branch] && inputNodeLs.push(node);
                    } else if ((node.nodeId.startsWith('output') && node.type === 'choose') || node.nodeId.startsWith('condition')) {
                        !nodeLMap[node.branch] && branchNodeLs.push(node);
                    }
                    nodeLMap[node.branch] = true;
                });
                return [inputNodeLs, outputNodeLs, branchNodeLs];
            },
            [[], [], []]
        );

        let result = findParallelNodes(inputNodeLs, branchNodeLs);
        if (result.length) {
            sendEvent([...result, []]);
            return [t('parallelInputOutputNodes')];
        }
        // if (!result.length) {
        //     result = findParallelNodes(outputNodeLs, branchNodeLs);
        //     if (result.length) {
        //         sendEvent([...result, []]);
        //         return [t('parallelOutputNodes')];
        //     }
        // }
        console.log('inputParallelNids, outputParallelNids :>> ', result);

        // 开始到结束流程是否完整
        const errorLine = branchLines.find(line => !line.end);
        if (errorLine) {
            sendEvent([errorLine.nodeIds[errorLine.nodeIds.length - 1].nodeId]);
            return [t('missingEndNode')];
        }

        // 找出分支节点
        const conditionOutputs = flow.nodes.reduce((res, node) => {
            if (node.data.type === "condition") {
                node.data.group_params[0].params[0].value.forEach(item => {
                    res.push({ name: node.data.name, nodeId: node.id, output: item.id });
                });
                res.push({ name: node.data.name, nodeId: node.id, output: "right_handle" });
            }
            return res;
        }, []);
        // 找出右侧没有链接的condtion节点
        const incompleteNode = conditionOutputs.find(output => {
            return !flow.edges.some(edge =>
                edge.source === output.nodeId && edge.sourceHandle === output.output
            );
        });
        if (incompleteNode) {
            sendEvent(incompleteNode.nodeId);
            return [t('unconnectedConditionNode', { nodeName: incompleteNode.name })];
        }

        sendEvent([]); // reduction
        return errors;
    };
};


// 技能版本管理
const useVersion = (flow) => {
    const { t } = useTranslation('flow')
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
            const currentvId = window.flow_version
            const currentV = data.find(el => currentvId ? el.id === currentvId : el.is_current === 1)
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
        isOnlineVersion: version?.id === onlineVid,
        isOnlineVersionFun: () => version.id === onlineVid,
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


// 离开页面保存提示
const useBeforeUnload = (flow, preFlow) => {
    const { t } = useTranslation()

    // 离开提示保存
    useEffect(() => {
        const fun = (e) => {
            var confirmationMessage = `${t('flow.unsavedChangesConfirmation')}`;
            (e || window.event).returnValue = confirmationMessage; // Compatible with different browsers
            return confirmationMessage;
        }
        window.addEventListener('beforeunload', fun);
        return () => { window.removeEventListener('beforeunload', fun) }
    }, [])

    const hasChanged = useMemo(() => {
        if (!flow) return false
        const oldFlowData = JSON.parse(preFlow)
        if (!oldFlowData) return true
        // 比较新旧
        const { edges, nodes } = flow
        const { edges: oldEdges, nodes: oldNodes } = oldFlowData
        const a = !(isEqual(edges, oldEdges) && isEqual(nodes, oldNodes))
        // console.log('12313132123 :>> ', a, isEqual(edges, oldEdges), isEqual(nodes, oldNodes));
        // console.log('nodes:>> ', nodes.find(el => el.id === "llm_214bb").data.group_params[2].params[1].value);
        // console.log('oldNodes:>> ', oldNodes.find(el => el.id === "llm_214bb").data.group_params[2].params[1].value);
        return a
    }, [preFlow, flow.nodes, flow.edges])

    return [useBlocker(hasChanged), hasChanged] as const;
}

export default Header;
