import FlowSetting from "@/components/Pro/security/FlowSetting";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { locationContext } from "@/contexts/locationContext";
import { ArrowLeft, ChevronUp } from "lucide-react";
import { useContext, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";
import L2ParameterComponent from "@/CustomNodes/GenericNode/components/parameterComponent/l2Index";
import ShadTooltip from "@/components/ShadTooltipComponent";
import { Button } from "@/components/bs-ui/button";
import { Input, Textarea } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { TabsContext } from "@/contexts/tabsContext";
import { userContext } from "@/contexts/userContext";
import { createCustomFlowApi, getFlowApi } from "@/controllers/API/flow";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { useHasForm } from "@/util/hook";
import FormSet from "./FormSet";
import Avator from "@/components/bs-ui/input/avator";
import { SkillIcon } from "@/components/bs-icons";
import { uploadFileWithProgress } from "@/modals/UploadModal/upload";

export default function l2Edit() {
    const { t } = useTranslation()

    const { id, vid } = useParams()
    const { appConfig } = useContext(locationContext)
    const { flow: nextFlow, setFlow, saveFlow } = useContext(TabsContext);
    const flow = useMemo(() => {
        return id ? nextFlow : null
    }, [nextFlow])

    const [isL2, setIsL2] = useState(false)
    const [loading, setLoading] = useState(false)
    const [name, setName] = useState('');
    const [description, setDescription] = useState('');
    const [guideWords, setGuideWords] = useState('');

    useEffect(() => {
        if (!id) return;

        getFlowApi(id).then(_flow => {
            setFlow('l2 flow init', _flow);
            setIsL2(true);
            setName(_flow.name);
            setDescription(_flow.description);
            setGuideWords(_flow.guide_word);
            setLogo(_flow.logo);
        });
    }, [id]);


    // 校验
    const { user } = useContext(userContext);
    const [error, setError] = useState({ name: false, desc: false }) // 表单error信息展示
    const { message } = useToast()
    const isParamError = (name, desc, showErrorConfirm = false) => {
        const errorlist = [];
        if (!name) errorlist.push(t('skills.skillNameRequired'));
        if (name.length > 30) errorlist.push(t('skills.skillNameTooLong'));

        // Duplicate name validation
        const nameErrors = errorlist.length;
        if (!desc) errorlist.push(t('skills.skillDescRequired'));
        if (desc.length > 200) errorlist.push(t('skills.skillDescTooLong'));
        if (errorlist.length && showErrorConfirm) message({
            title: t('prompt'),
            variant: 'error',
            description: errorlist
        });
        setError({ name: !!nameErrors, desc: errorlist.length > nameErrors });

        return !!errorlist.length;
    }


    const navigate = useNavigate()
    const flowSettingSaveRef = useRef(null)
    // 创建新技能 
    const handleCreateNewSkill = async () => {
        if (isParamError(name, description, true)) return
        setLoading(true)

        await captureAndAlertRequestErrorHoc(createCustomFlowApi({
            logo,
            name,
            description,
            guide_word: guideWords
        }, user.user_name).then(newFlow => {
            setFlow('l2 create flow', newFlow)
            navigate("/skill/" + newFlow.id, { replace: true }); // l3
            // 创建技能后在保存
            flowSettingSaveRef.current?.(newFlow.id)
        }))
        setLoading(false)
    }

    const formRef = useRef(null)

    // 编辑回填参数
    const handleJumpFlow = async () => {
        // 上线技能直接跳转L3
        if (flow.status === 2) return navigate('/skill/' + id, { replace: true })
        // 高级配置信息有误直接跳转L3
        if (isParamError(name, description)) return navigate('/skill/' + id, { replace: true })
        // 保存在跳
        setLoading(true)
        formRef.current?.save()

        await saveFlow({ ...flow, name, description, guide_word: guideWords, logo })
        setLoading(false)
        navigate('/skill/' + id, { replace: true })
    }

    const handleSave = async () => {
        if (isParamError(name, description, true)) return
        setLoading(true)
        formRef.current?.save()

        const res = await captureAndAlertRequestErrorHoc(saveFlow({ ...flow, name, description, guide_word: guideWords, logo }))
        setLoading(false)
        if (res) {
            message({
                title: t('prompt'),
                variant: 'success',
                description: t('saved')
            });
            setTimeout(() => /^\/skill\/[\w\d-]+/.test(location.pathname) && navigate(-1), 2000);
        }
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

    // 头像
    const [logo, setLogo] = useState('')
    const uploadAvator = (file) => {
        uploadFileWithProgress(file, (progress) => { }, 'icon').then(res => {
            setLogo(res.file_path);
        })
    }

    return <div className="relative box-border h-full overflow-auto">
        <div className="p-6 pb-48 h-full overflow-y-auto">
            <div className="flex justify-between w-full">
                <ShadTooltip content={t('back')} side="right">
                    <button className="extra-side-bar-buttons w-[36px]" onClick={() => window.history.length < 3 ? navigate('/build/apps') : navigate(-1)}>
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
                            <Label htmlFor="name">{t('skills.avatar')}</Label>
                            <Avator value={logo} className="mt-2" onChange={uploadAvator}><SkillIcon className="bg-primary w-9 h-9 rounded-sm" /></Avator>
                        </div>
                        <div className="mt-4">
                            <Label htmlFor="name">{t('skills.skillName')}</Label>
                            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder={t('skills.skillName')} className={`mt-2 ${error.name && 'border-red-400'}`} />
                        </div>
                        <div className="mt-4">
                            <Label htmlFor="username">{t('skills.description')}</Label>
                            <Textarea value={description} onChange={(e) => setDescription(e.target.value)} id="name" placeholder={t('skills.description')} className={`mt-2 ${error.desc && 'border-red-400'}`} />
                        </div>
                        <div className="mt-4">
                            <Label htmlFor="username">{t('skills.guideWords')}</Label>
                            <Textarea value={guideWords} onChange={(e) => setGuideWords(e.target.value)} maxLength={1000} id="name" placeholder={t('skills.guideWords')} className={`mt-2 ${error.desc && 'border-red-400'}`} />
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
                    {isForm && <FormSet ref={formRef} id={id} vid={vid}></FormSet>}
                    {/* 安全审查 */}
                    {appConfig.isPro && <div>
                        <p className="text-center text-gray-400 mt-8 cursor-pointer flex justify-center" onClick={showContent}>
                            {t('build.contentSecuritySettings')}
                            <ChevronUp />
                        </p>
                        {/* base form */}
                        <div className="w-full overflow-hidden transition-all px-1">
                            <FlowSetting id={id} type={2} isOnline={nextFlow?.status === 2} onSubTask={(fn) => flowSettingSaveRef.current = fn} />
                        </div>
                    </div>}
                </div>
            </div>
        </div>
        {/* footer */}
        <div className="absolute flex z-30 bottom-0 w-[calc(100vw-200px)] py-8 mr-5 justify-center bg-background-login">
            {
                isL2 ?
                    <div className="flex gap-4 w-[50%]">
                        <Button disabled={loading} className="extra-side-bar-save-disable w-[70%]" onClick={handleSave}>
                            {t('save')}
                        </Button>
                        <Button disabled={loading} className="w-[30%]" variant="outline" onClick={() => handleJumpFlow()}>
                            {t('skills.advancedConfiguration')}
                        </Button>
                    </div>
                    :
                    <div className="flex justify-center w-[50%]">
                        <Button disabled={loading} className="extra-side-bar-save-disable w-[50%]" onClick={handleCreateNewSkill}>
                            {t('skills.nextStep')}
                        </Button>
                    </div>
            }
        </div>
    </div>
};
