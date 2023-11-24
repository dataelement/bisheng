import { ArrowLeft, ChevronDown } from "lucide-react";
import { useContext, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";
import L2ParameterComponent from "../../CustomNodes/GenericNode/components/parameterComponent/l2Index";
import ShadTooltip from "../../components/ShadTooltipComponent";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Textarea } from "../../components/ui/textarea";
import { alertContext } from "../../contexts/alertContext";
import { TabsContext } from "../../contexts/tabsContext";
import { userContext } from "../../contexts/userContext";
import { getFlowFromDatabase } from "../../controllers/API";
import FormSet from "./components/FormSet";
import { useHasReport } from "../../util/hook";

export default function l2Edit() {

    const [isL2, setIsL2] = useState(false)
    const navigate = useNavigate()
    const { t } = useTranslation()
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

    const { user } = useContext(userContext);
    const [error, setError] = useState({ name: false, desc: false })
    const isParamError = (name, desc, noError = false) => {
        const errorlist = [];
        if (!name) errorlist.push(t('skills.skillNameRequired'));
        if (name.length > 30) errorlist.push(t('skills.skillNameTooLong'));

        // Duplicate name validation
        if (flows.find(flow => flow.name === name && flow.user_id === user.user_id && flow.id !== id)) errorlist.push(t('skills.skillNameExists'));
        const nameErrors = errorlist.length;
        if (!desc) errorlist.push(t('skills.skillDescRequired'));
        if (desc.length > 200) errorlist.push(t('skills.skillDescTooLong'));
        if (errorlist.length && !noError) setErrorData({
            title: t('skills.errorTitle'),
            list: errorlist,
        });
        setError({ name: !!nameErrors, desc: errorlist.length > nameErrors });
        return !!errorlist.length;
    }

    const formRef = useRef(null)

    // 编辑回填参数
    const { id } = useParams()
    const handleJumpFlow = async () => {
        const name = nameRef.current.value
        const description = descRef.current.value
        if (isParamError(name, description, true)) return navigate('/flow/' + id, { replace: true })
        // 保存在跳
        setLoading(true)
        formRef.current?.save()
        await saveFlow({ ...flow, name, description });
        setLoading(false)
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
        setLoading(true)
        formRef.current?.save()
        await saveFlow(flow);
        setLoading(false)
        setSuccessData({ title: t('success') });
        setTimeout(() => /^\/skill\/[\w\d-]+/.test(location.pathname) && navigate(-1), 2000);
    }

    const showContent = (e) => {
        const target = e.target.tagName === 'svg' ? e.target.parentNode : e.target
        const contentDom = target.nextSibling
        target.children[0].style.transform = contentDom.clientHeight ? 'rotate(180deg)' : 'rotate(0deg)'
        contentDom.style.maxHeight = contentDom.clientHeight ? 0 : '999px'
    }

    // isreport
    const isReport = useHasReport(flow)

    return <div className="relative box-border">
        <div className="p-6  pb-24 h-screen overflow-y-auto">
            <div className="flex justify-between w-full">
                <ShadTooltip content={t('back')} side="right">
                    <button className="extra-side-bar-buttons w-[36px]" onClick={() => navigate(-1)}>
                        <ArrowLeft strokeWidth={1.5} className="side-bar-button-size" />
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
                <p className="text-center text-2xl">{t('skills.skillSettings')}</p>
                <div className="group w-[80%] mx-auto grid gap-4 py-4">
                    <p className="text-center text-gray-400 mt-4 cursor-pointer flex justify-center" onClick={showContent}>{t('skills.basicInfo')}
                        <ChevronDown />
                    </p>
                    <div className="grid gap-4 overflow-hidden transition-all">
                        <div className="grid grid-cols-4 items-center gap-4">
                            <Label htmlFor="name" className="text-right">{t('skills.skillName')}</Label>
                            <Input ref={nameRef} placeholder={t('skills.skillName')} className={`col-span-2 ${error.name && 'border-red-400'}`} />
                        </div>
                        <div className="grid grid-cols-4 items-center gap-4">
                            <Label htmlFor="username" className="text-right">{t('skills.description')}</Label>
                            <Textarea ref={descRef} id="name" placeholder={t('skills.description')} className={`col-span-2 ${error.desc && 'border-red-400'}`} />
                        </div>
                    </div>
                    {
                        isL2 && <div className="mt-4">
                            <p className="text-center pr-2 text-gray-400 cursor-pointer flex justify-center" onClick={showContent}>{t('skills.parameterInfo')}
                                <ChevronDown />
                            </p>
                            <div className="grid gap-4 overflow-hidden transition-all">
                                {flow?.data?.nodes.map(({ data }) => (
                                    <div key={data.id}>
                                        <div className="only:hidden grid-cols-4 mt-6">
                                            <span className=" p-2 font-bold text-gray-400 ml-[18%] text-base">
                                                {data.node.l2_name || data.node.display_name}
                                            </span>
                                        </div>
                                        {
                                            Object.keys(data.node.template).map(k => (
                                                data.node.template[k].l2 && <div className="grid grid-cols-4 items-center gap-4" key={k}>
                                                    <Label htmlFor="name" className="text-right">
                                                        {data.node.template[k].l2_name || data.node.template[k].name}
                                                    </Label>
                                                    <L2ParameterComponent data={data} type={data.node.template[k].type} name={k} />
                                                </div>
                                            ))
                                        }
                                    </div>
                                ))}
                            </div>
                        </div>
                    }
                    {/* 表单设置 */}
                    {isReport && <FormSet ref={formRef} id={id}></FormSet>}
                </div>
            </div>
        </div>
        <div className="absolute flex bottom-0 w-full py-8 justify-center bg-[#fff] border-t">
            {
                isL2 ?
                    <div className="flex gap-4 w-[50%]">
                        <Button disabled={loading} className="extra-side-bar-save-disable w-[70%] rounded-full" onClick={handleSave}>
                            {t('save')}
                        </Button>
                        <Button disabled={loading} className="w-[30%] rounded-full" variant="outline" onClick={() => handleJumpFlow()}>
                            {t('skills.advancedConfiguration')}
                        </Button>
                    </div>
                    :
                    <div className="flex justify-center w-[50%]">
                        <Button disabled={loading} className="extra-side-bar-save-disable w-[50%] rounded-full" onClick={handleCreateNewSkill}>
                            {t('skills.nextStep')}
                        </Button>
                    </div>
            }
        </div>
    </div>
};
