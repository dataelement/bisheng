import { AssistantIcon } from "@/components/bs-icons";
import { LoadIcon } from "@/components/bs-icons/loading";
import { Accordion } from "@/components/bs-ui/accordion";
import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogClose, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { Input, Textarea } from "@/components/bs-ui/input";
import Avator from "@/components/bs-ui/input/avator";
import { generateUUID } from "@/components/bs-ui/utils";
import AssistantSetting from "@/components/Pro/security/AssistantSetting";
import { locationContext } from "@/contexts/locationContext";
import { getCommitmentApi, readTempsDatabase, setCommitmentApi } from "@/controllers/API";
import { createAssistantsApi } from "@/controllers/API/assistant"; // 假设有对应的接口
import { getAssistantModelConfig, getLlmDefaultModel } from "@/controllers/API/finetune";
import { copyReportTemplate, createWorkflowApi } from "@/controllers/API/workflow";
// import { createWorkflowApi, getWorkflowApi, updateWorkflowApi } from "@/controllers/API/workflow"; // 假设有对应的接口
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { uploadFileWithProgress } from "@/modals/UploadModal/upload";
import { AppType } from "@/types/app";
import { forwardRef, useContext, useImperativeHandle, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { SelectCommitment } from "../ChatAppPage/components/CommitmentDialog";

type ModalProps = {};
type ModalRef = {
    open: (type: string, id?: number) => void;
    edit: (type: string, appId: string) => void;
};

const CreateApp = forwardRef<ModalRef, ModalProps>(({ onSave }, ref) => {
    const [open, setOpen] = useState(false);
    const [formData, setFormData] = useState({
        url: '',
        name: '',
        desc: '',
    });
    const [appType, setType] = useState<AppType>(AppType.ASSISTANT); // 判断是助手还是工作流
    const [isEditMode, setIsEditMode] = useState(false); // 区分编辑模式
    const [loading, setLoading] = useState(false);
    const { t } = useTranslation('flow');
    const { appConfig } = useContext(locationContext)
    const securityRef = useRef<any>(null);
    // 承诺书id
    const [commitmentId, setCommitmentId] = useState<string>('');

    // 应用id (edit)
    const [appId, setAppId] = useState<string>('');
    const onlineRef = useRef(false);

    // State for errors
    const [errors, setErrors] = useState<any>({});

    useImperativeHandle(ref, () => ({
        // create
        open(type: AppType, tempId?: number) {
            setType(type);
            setIsEditMode(false);
            setFormData({
                url: '',
                name: '',
                desc: AppType.ASSISTANT === type ? `${t('build.example', { ns: 'bs' })}：
${t('build.exampleOne', { ns: 'bs' })}
${t('build.exampleTwo', { ns: 'bs' })}
1. XX
2. XX
3. …` : '',
            });
            if (tempId) {
                handleSelectTemplate(type, tempId);
            }
            setErrors({})
            setOpen(true);
            tempDataRef.current = null;
            setAppId('');
        },
        // edit
        edit(type: AppType, flow: any) {
            setType(type);
            setIsEditMode(true);
            fetchDetails(type, flow);
            setErrors({})
            setOpen(true);
            tempDataRef.current = null;
            setAppId(flow.id);
            onlineRef.current = flow.status === 2
            // 承诺书
            if (appConfig.securityCommitment) {
                getCommitmentApi(flow.id).then(res => {
                    setCommitmentId(res.length ? res[0].promise_id : '');
                })
            }
        },
    }));

    // 从模板中选择
    const tempDataRef = useRef<any>(null);
    const handleSelectTemplate = async (type: AppType, tempId: number) => {
        const [flow] = await readTempsDatabase('flow', tempId)
        tempDataRef.current = flow;
        setFormData({
            url: flow.logo || '',
            name: `${flow.name}-${generateUUID(5)}`,
            desc: flow.description
        });
    }

    // 根据 type 和 id 获取详情（编辑模式）
    const fetchDetails = async (type: AppType, flow: any) => {
        setFormData({
            url: flow.logo,
            name: flow.name,
            desc: flow.description,
        });
    };

    // Validate form fields
    const validateField = (name: string, value: string) => {
        switch (name) {
            case 'name':
                if (value.length > 50) return AppType.ASSISTANT === appType ? t('maxNameLengthAssistant') : t('maxNameLengthWorkflow');
                return '';
            case 'desc':
                if (AppType.ASSISTANT === appType && value.length < 20) return t('minDescLengthAssistant');
                return '';
            default:
                return '';
        }
    };

    // Handle field change
    const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
        const { name, value } = e.target;
        const error = validateField(name, value);
        setFormData(prev => ({ ...prev, [name]: value }));
        setErrors(prev => ({ ...prev, [name]: error }));
    };

    // Validate entire form
    const validateForm = () => {
        const formErrors: any = {};
        let isValid = true;

        Object.keys(formData).forEach(key => {
            const error = validateField(key, formData[key]);
            if (error) {
                formErrors[key] = error;
                isValid = false;
            }
        });

        setErrors(formErrors);
        return isValid;
    };

    // Handle form submission
    const navigate = useNavigate()
    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        const isValid = validateForm();
        if (!isValid) return;

        setLoading(true);
        if (isEditMode) {
            // 编辑
            setLoading(false);
            setOpen(false);

            !onlineRef.current && appConfig.securityCommitment && setCommitmentApi(appId, commitmentId)
            // 修改成功
            return onSave({
                name: formData.name,
                description: formData.desc,
                logo: formData.url
            })
        }

        // let res = null
        if (tempDataRef.current) {
            // 创建by模板
            if (AppType.FLOW === appType) {
                // 复制报告节点中报告模板
                for (let i = 0; i < tempDataRef.current.data.nodes.length; i++) {
                    const node = tempDataRef.current.data.nodes[i];
                    await copyReportTemplate(node.data)
                }

                // 使用默认模型 清空知识库和工具
                const [workflow, assistant] = await Promise.all([getLlmDefaultModel(), getAssistantModelConfig()])
                const workflowModelId = workflow.model_id
                const assistantModelId = assistant.llm_list.find(item => item.default).model_id
                delete tempDataRef.current.data.source

                tempDataRef.current.data.nodes.forEach(node => {
                    if (['rag', 'llm', 'agent', 'qa_retriever'].includes(node.data.type)) {
                        node.data.group_params.forEach(group =>
                            group.params.forEach(param => {
                                if (param.type === 'bisheng_model') {
                                    param.value = workflowModelId
                                } else if (param.type === 'agent_model') {
                                    param.value = assistantModelId
                                } else if (param.type === 'knowledge_select_multi' && param.value.type !== 'tmp') {
                                    param.value.value = []
                                } else if (param.type === 'qa_select_multi') {
                                    param.value = []
                                } else if (param.type === 'add_tool') {
                                    param.value = []
                                }
                            })
                        )
                    }
                })
                const res = await captureAndAlertRequestErrorHoc(createWorkflowApi(formData.name, formData.desc, formData.url, tempDataRef.current))
                appConfig.securityCommitment && setCommitmentApi(res.id, commitmentId)
                if (res) navigate('/flow/' + res.id)
            }
        } else {
            // 创建
            if (appType === AppType.ASSISTANT) {
                const res = await captureAndAlertRequestErrorHoc(createAssistantsApi(formData.name, formData.desc, formData.url))
                appConfig.securityCommitment && setCommitmentApi(res.id, commitmentId)
                if (res) {
                    //@ts-ignore
                    window.assistantCreate = true // 标记新建助手
                    navigate('/assistant/' + res.id)
                }
            } else {
                if (appId) return navigate('/flow/' + appId) // 避免重复创建
                // 创建工作流
                const workflow = await captureAndAlertRequestErrorHoc(createWorkflowApi(formData.name, formData.desc, formData.url))
                appConfig.securityCommitment && setCommitmentApi(workflow.id, commitmentId)
                if (workflow) {
                    const navigateToFlow = (id) => navigate(`/flow/${id}`);
                    // 非Pro版本直接跳转
                    if (!appConfig.isPro) return navigateToFlow(workflow.id)

                    setAppId(workflow.id)
                    const securityCreated = await securityRef.current.create(workflow.id)
                    if (securityCreated) navigateToFlow(workflow.id)
                }
            }
        }
        setLoading(false);
    };

    // 上传头像逻辑
    const uploadAvator = (file: File) => {
        uploadFileWithProgress(file, (progress) => { }, 'icon').then(res => {
            setFormData(prev => ({ ...prev, url: '/bisheng/' + res.relative_path }));
        });
    };

    return (
        <Dialog open={open} onOpenChange={setOpen}>
            <DialogContent className="sm:max-w-[625px] bg-background-login">
                <DialogHeader>
                    <DialogTitle>{isEditMode ? t('edit') : t('create')}{appType === AppType.ASSISTANT ? t('assistant') : t('workflow')}</DialogTitle>
                </DialogHeader>
                <div className="flex flex-col mt-2">
                    <div className="mb-6">
                        <label htmlFor="name" className="bisheng-label">
                            {appType === AppType.ASSISTANT ? t('assistantAvatar') : t('workflowAvatar')}
                        </label>
                        <Avator value={formData.url} className="mt-3" onChange={uploadAvator}>
                            <AssistantIcon className="bg-primary w-8 h-8 rounded-sm" />
                        </Avator>
                    </div>
                    <div className="mb-6">
                        <label htmlFor="name" className="bisheng-label">
                            {appType === AppType.ASSISTANT ? t('build_assistantName') : t('name')}
                            <span className="bisheng-tip">*</span>
                        </label>
                        <Input
                            id="name"
                            name="name"
                            maxLength={50}
                            showCount
                            placeholder={appType === AppType.ASSISTANT ? t('giveAssistantAName') : t('giveWorkflowAName')}
                            className="mt-3"
                            value={formData.name}
                            onChange={handleChange}
                        />
                        {errors.name && <p className="bisheng-tip mt-1">{errors.name}</p>}
                    </div>
                    <div className="mb-6">
                        <label htmlFor="desc" className="bisheng-label">
                            {appType === AppType.ASSISTANT ? t('build_roleAndTasks') : t('description')}
                        </label>
                        <Textarea
                            id="desc"
                            name="desc"
                            placeholder={appType === AppType.ASSISTANT ? t('build_forExample') : t('enterWorkflowDescription')}
                            maxLength={appType === AppType.ASSISTANT ? 1000 : undefined}
                            className="mt-3 min-h-32 pt-3"
                            value={formData.desc}
                            onChange={handleChange}
                        />
                        {errors.desc && <p className="bisheng-tip mt-1">{errors.desc}</p>}
                    </div>
                    {appConfig.securityCommitment && <div className="mb-6">
                        <label className="bisheng-label">承诺书:</label>
                        <SelectCommitment value={commitmentId} onChange={setCommitmentId} />
                    </div>}
                </div>
                {/* 工作流安全审查 */}
                <div className={isEditMode ? '' : 'hidden'}>
                    {appConfig.isPro && <Accordion type="multiple" className="w-full">
                        <AssistantSetting ref={securityRef} id={appId} type={5} />
                    </Accordion>}
                </div>
                <DialogFooter>
                    <DialogClose>
                        <Button variant="outline" className="px-11" type="button" onClick={() => setFormData({ name: '', desc: '', url: '' })}>
                            {t('cancel')}
                        </Button>
                    </DialogClose>
                    <Button disabled={!formData.name || loading} type="submit" className="px-11" onClick={handleSubmit}>
                        {loading && <LoadIcon className="mr-2" />}
                        {t(isEditMode ? 'save' : 'create')}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
});

export default CreateApp;
