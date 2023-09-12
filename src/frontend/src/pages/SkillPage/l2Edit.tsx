import { ArrowLeft } from "lucide-react";
import { useContext, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import L2ParameterComponent from "../../CustomNodes/GenericNode/components/parameterComponent/l2Index";
import ShadTooltip from "../../components/ShadTooltipComponent";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Textarea } from "../../components/ui/textarea";
import { alertContext } from "../../contexts/alertContext";
import { TabsContext } from "../../contexts/tabsContext";
import { getFlowFromDatabase } from "../../controllers/API";

export default function l2Edit() {

    const [isL2, setIsL2] = useState(false)
    const navigate = useNavigate()

    // form 
    const nameRef = useRef(null)
    const descRef = useRef(null)
    const [loading, setLoading] = useState(false)
    // submit 
    const { setErrorData } = useContext(alertContext);
    const { flows, tabId, addFlow, saveFlow } = useContext(TabsContext);
    const { setSuccessData } = useContext(alertContext);
    const handleCreateNewSkill = async () => {
        if (isParamError(nameRef.current.value, descRef.current.value)) return
        setLoading(true)
        const id = await addFlow({ id: '', data: null, name: nameRef.current.value, description: descRef.current.value, status: 1 }, true)
        navigate("/flow/" + id, { replace: true });
        setLoading(false)
    }

    const [error, setError] = useState({ name: false, desc: false })
    const isParamError = (name, desc, noError = false) => {
        const errorlist = []
        if (!name) errorlist.push('请填写技能名称')
        if (name.length > 30) errorlist.push('技能名称过长，不要超过30字')

        // 重名校验
        if (flows.find(flow => flow.name === name && flow.id !== id)) errorlist.push('该名称已存在')
        const nameErrors = errorlist.length
        if (!desc) errorlist.push('请填写技能描述') // 加些描述能够快速让别人理解您创造的技能')
        if (desc.length > 200) errorlist.push('技能描述过长，不要超过200字')
        if (errorlist.length && !noError) setErrorData({
            title: "关键信息有误",
            list: errorlist,
        });
        setError({ name: !!nameErrors, desc: errorlist.length > nameErrors })
        return !!errorlist.length
    }

    // 编辑回填参数
    const { id } = useParams()
    const handleJumpFlow = async () => {
        const name = nameRef.current.value
        const description = descRef.current.value
        if (isParamError(name, description, true)) return navigate('/flow/' + id, { replace: true })
        // // 保存在跳
        await saveFlow({ ...flow, name, description });
        navigate('/flow/' + id, { replace: true })
    }

    const [flow, setFlow] = useState(null)
    useEffect(() => {
        if (!id || flows.length === 0) return
        const loadFlow = async () => {
            let flow = flows.find(_flow => _flow.id === id)
            if (!flow) {
                flow = await getFlowFromDatabase(id)
                flows.push(flow)
            }
            setIsL2(true)
            setFlow(flow)
            nameRef.current.value = flow.name
            descRef.current.value = flow.description
        }
        loadFlow()
    }, [id, flows])

    const handleSave = async () => {
        flow.name = nameRef.current.value
        flow.description = descRef.current.value
        if (isParamError(flow.name, flow.description)) return
        await saveFlow(flow);
        setSuccessData({ title: "保存成功" });
        setTimeout(() => {
            navigate(-1)
        }, 2000);
    }

    return <div className="p-6 h-screen overflow-y-auto">
        <div className="flex justify-between w-full">
            {/* <button className="extra-side-bar-save-disable" ><ArrowLeft /></button> */}
            <ShadTooltip content="返回" side="right">
                <button className="extra-side-bar-buttons w-[36px]" onClick={() => navigate(-1)} >
                    <ArrowLeft strokeWidth={1.5} className="side-bar-button-size " ></ArrowLeft>
                </button>
            </ShadTooltip>
            {/* <ShadTooltip content="接口信息" side="left">
                <button className="extra-side-bar-buttons w-[36px]" onClick={() => openPopUp(<ApiModal flow={flows.find((f) => f.id === tabId)} />)} >
                    <TerminalSquare strokeWidth={1.5} className="side-bar-button-size " ></TerminalSquare>
                </button>
            </ShadTooltip> */}
        </div>
        {/* form */}
        <div className="mt-6">
            <p className="text-center text-2xl">技能设置</p>
            <div className="w-[80%] mx-auto grid gap-4 py-4">
                <p className="text-center text-gray-400 mt-4">基础信息</p>
                <div className="grid grid-cols-4 items-center gap-4">
                    <Label htmlFor="name" className="text-right">技能名称</Label>
                    <Input ref={nameRef} placeholder="技能名称" className={`col-span-2 ${error.name && 'border-red-400'}`} />
                </div>
                <div className="grid grid-cols-4 items-center gap-4">
                    <Label htmlFor="username" className="text-right">描述</Label>
                    <Textarea ref={descRef} id="name" placeholder="技能描述" className={`col-span-2 ${error.desc && 'border-red-400'}`} />
                </div>
                {
                    isL2 && <div className="mt-4">
                        <p className="text-center pr-2 text-gray-400">参数信息</p>
                        {flow?.data?.nodes.map(({ data }) => (
                            Object.keys(data.node.template).map(k => (
                                data.node.template[k].l2 && <div className="grid grid-cols-4 items-center gap-4">
                                    <Label htmlFor="name" className="text-right">{data.node.template[k].l2_name}</Label>
                                    <L2ParameterComponent key={k} data={data} type={data.node.template[k].type} name={k} />
                                </div>
                            ))
                        ))}
                    </div>
                }
                {
                    isL2 ? <div className="m-10 w-[50%] mx-auto">
                        {/* <TooltipProvider>
                            <Tooltip>
                                <TooltipTrigger><button className="inline-flex text-xs gap-1 text-blue-500" onClick={() => handleJumpFlow()}><Workflow size={16} />高级配置</button></TooltipTrigger>
                                <TooltipContent className="bg-gray-50 rounded-full"><p>流程图</p></TooltipContent>
                            </Tooltip>
                        </TooltipProvider> */}
                        {/* <Button className="extra-side-bar-save-disable" >技能校验</Button> */}
                        <div className="flex gap-4">
                            <Button className="extra-side-bar-save-disable w-[70%] rounded-full" onClick={handleSave} >保存</Button>
                            <Button className="w-[30%] rounded-full" variant="outline" onClick={() => handleJumpFlow()} >高级配置</Button>
                        </div>
                    </div> :
                        <div className="flex justify-center m-4">
                            <Button disabled={loading} className="extra-side-bar-save-disable w-[50%] mt-8 rounded-full" onClick={handleCreateNewSkill}>下一步，高级配置</Button>
                        </div>
                }
            </div>
        </div>
    </div>
};
