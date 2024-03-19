import { ArrowLeft, ChevronUp } from "lucide-react";
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
import { createCustomFlowApi, getFlowApi } from "../../controllers/API/flow";
import { useHasForm } from "../../util/hook";
import FormSet from "./components/FormSet";
import { captureAndAlertRequestErrorHoc } from "../../controllers/request";

export default function l2Edit() {
    const { t } = useTranslation()

    const { id } = useParams()
    const { flow: nextFlow, setFlow, saveFlow } = useContext(TabsContext);
    const { setErrorData, setSuccessData } = useContext(alertContext);
    const flow = useMemo(() => {
        return id ? nextFlow : null
    }, [nextFlow])

    const [isL2, setIsL2] = useState(false)
    const [loading, setLoading] = useState(false)
    const nameRef = useRef(null)
    const descRef = useRef(null)
    const guideRef = useRef(null)

    useEffect(() => {
        // 无id不再请求
        if (!id) return
        // 已有flow 数据时，不再请求
        if (flow?.id === id) {
            setIsL2(true)
            nameRef.current.value = flow.name
            descRef.current.value = flow.description
            guideRef.current.value = flow.guide_word
            return
        }
        // 无flow从db获取
        getFlowApi(id).then(_flow => {
            // 回填flow
            setFlow('l2 flow init', _flow)
            setIsL2(true)
            nameRef.current.value = _flow.name
            descRef.current.value = _flow.description
            guideRef.current.value = _flow.guide_word
        })
    }, [id])


    // 校验
    const { user } = useContext(userContext);
    const [error, setError] = useState({ name: false, desc: false }) // 表单error信息展示
    const isParamError = (name, desc, showErrorConfirm = false) => {
        const errorlist = [];
        if (!name) errorlist.push(t('skills.skillNameRequired'));
        if (name.length > 30) errorlist.push(t('skills.skillNameTooLong'));

        // Duplicate name validation
        const nameErrors = errorlist.length;
        if (!desc) errorlist.push(t('skills.skillDescRequired'));
        if (desc.length > 200) errorlist.push(t('skills.skillDescTooLong'));
        if (errorlist.length && showErrorConfirm) setErrorData({
            title: t('skills.errorTitle'),
            list: errorlist,
        });
        setError({ name: !!nameErrors, desc: errorlist.length > nameErrors });
        return !!errorlist.length;
    }


    const navigate = useNavigate()
    // 创建新技能 
    const handleCreateNewSkill = async () => {
        const name = nameRef.current.value
        const guideWords = guideRef.current.value
        const description = descRef.current.value
        if (isParamError(name, description, true)) return
        setLoading(true)

        await captureAndAlertRequestErrorHoc(createCustomFlowApi({
            name,
            description,
            guide_word: guideWords
        }, user.user_name).then(newFlow => {
            setFlow('l2 create flow', newFlow)
            navigate("/flow/" + newFlow.id, { replace: true }); // l3
        }))
        setLoading(false)
    }


    const formRef = useRef(null)

    // 编辑回填参数
    const handleJumpFlow = async () => {
        const name = nameRef.current.value
        const description = descRef.current.value
        const guideWords = guideRef.current.value
        // 高级配置信息有误直接跳转L3
        if (isParamError(name, description)) return navigate('/flow/' + id, { replace: true })
        // 保存在跳
        setLoading(true)
        formRef.current?.save()

        await saveFlow({ ...flow, name, description, guide_word: guideWords })
        setLoading(false)
        navigate('/flow/' + id, { replace: true })
    }

    const handleSave = async () => {
        const name = nameRef.current.value
        const description = descRef.current.value
        const guideWords = guideRef.current.value
        if (isParamError(name, description)) return
        setLoading(true)
        formRef.current?.save()

        await saveFlow({ ...flow, name, description, guide_word: guideWords })
        setLoading(false)
        setSuccessData({ title: t('success') });
        setTimeout(() => /^\/skill\/[\w\d-]+/.test(location.pathname) && navigate(-1), 2000);
    }

    // 表单收缩
    const showContent = (e) => {
        const target = e.target.tagName === 'svg' ? e.target.parentNode : e.target
        const contentDom = target.nextSibling
        target.children[0].style.transform = contentDom.clientHeight ? 'rotate(180deg)' : 'rotate(0deg)'
        contentDom.style.maxHeight = contentDom.clientHeight ? 0 : '999px'
    }

    // isForm
    const isForm = useHasForm(flow)

    return <div className="relative box-border">
        <div className="p-6 pb-48 h-screen overflow-y-auto">
            <div className="flex justify-between w-full">
                <ShadTooltip content={t('back')} side="right">
                    <button className="extra-side-bar-buttons w-[36px]" onClick={() => window.history.length < 3 ? navigate('/skills') : navigate(-1)}>
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
            <div className="pt-6">
                <p className="text-center text-2xl">{t('skills.skillSettings')}</p>
                <div className="w-[50%] max-w-2xl mx-auto">
                    <p className="text-center text-gray-400 mt-4 cursor-pointer flex justify-center" onClick={showContent}>
                        {t('skills.basicInfo')}
                        <ChevronUp />
                    </p>
                    {/* base form */}
                    <div className="w-full overflow-hidden transition-all px-1">
                        <div className="mt-4">
                            <Label htmlFor="name">{t('skills.skillName')}</Label>
                            <Input ref={nameRef} placeholder={t('skills.skillName')} className={`mt-2 ${error.name && 'border-red-400'}`} />
                        </div>
                        <div className="mt-4">
                            <Label htmlFor="username">{t('skills.description')}</Label>
                            <Textarea ref={descRef} id="name" placeholder={t('skills.description')} className={`mt-2 ${error.desc && 'border-red-400'}`} />
                        </div>
                        <div className="mt-4">
                            <Label htmlFor="username">{t('skills.guideWords')}</Label>
                            <Textarea ref={guideRef} maxLength={1000} id="name" placeholder={t('skills.guideWords')} className={`mt-2 ${error.desc && 'border-red-400'}`} />
                        </div>
                    </div>
                    {
                        // L2 form
                        isL2 && <div className="w-full mt-8">
                            <p className="text-center text-gray-400 cursor-pointer flex justify-center" onClick={showContent}>
                                {t('skills.parameterInfo')}
                                <ChevronUp />
                            </p>
                            <div className="w-full overflow-hidden transition-all px-1">
                                {flow?.data?.nodes.map(({ data }) => (
                                    <div key={data.id} className="w-full">
                                        <div className="only:hidden mt-6">
                                            <span className="p-2 font-bold text-gray-400 text-base">
                                                {data.node.l2_name || data.node.display_name}
                                            </span>
                                        </div>
                                        {
                                            // 自定义组件
                                            Object.keys(data.node.template).map(k => (
                                                data.node.template[k].l2 && <div className="w-full mt-4 px-1" key={k}>
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
                    {isForm && <FormSet ref={formRef} id={id}></FormSet>}
                </div>
            </div>
        </div>
        {/* footer */}
        <div className="absolute flex bottom-0 w-full py-8 justify-center bg-[#fff] border-t dark:bg-gray-900">
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
