// @ts-strict-ignore
import { Button, Input, Textarea } from '@bisheng/ui';
import AppAvator from "@/components/bs-comp/cardComponent/avatar";
import { Outlined } from "bisheng-icons";

import { Accordion } from "@/components/bs-ui/accordion";

import { Dialog,DialogClose,DialogContent,DialogFooter,DialogHeader,DialogTitle } from "@/components/bs-ui/dialog";

import Avator from "@/components/bs-ui/input/avator";
import { generateUUID } from "@/components/bs-ui/utils";
import AssistantSetting from "@/components/Pro/security/AssistantSetting";
import { locationContext } from "@/contexts/locationContext";
import { readTempsDatabase } from "@/controllers/API";
import { createAssistantsApi } from "@/controllers/API/assistant";
import { getAssistantModelConfig,getLlmDefaultModel } from "@/controllers/API/finetune";
import { copyReportTemplate,createWorkflowApi } from "@/controllers/API/workflow";
import { showApiError } from "@/controllers/request";
import { uploadFileWithProgress } from "@/modals/UploadModal/upload";
import { AppType,AppTypeToNum } from "@/types/app";
import { forwardRef,useContext,useEffect,useImperativeHandle,useMemo,useRef,useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { assistantRoleExample } from "./assistant/editAssistant/roleExample";
import { instantiateAssistantTemplate, type AssistantTemplateDraft } from './assistantTemplate';

type ModalProps = {};
type ModalRef = {
    open: (type: string, tempId?: number, data?: { id?: string, logo?: string, type?: AppType }) => void;
    edit: (type: string, appId: string) => void;
};

const CreateApp = forwardRef<ModalRef, ModalProps & { loca?: any }>(
    ({ onSave, loca }, ref) => {
        const [open, setOpen] = useState(false);
        const [formData, setFormData] = useState({
            url: '',
            name: '',
            desc: '',
        });
        const [appType, setType] = useState<AppType>(AppType.ASSISTANT); // assistant or workflow
        const [isEditMode, setIsEditMode] = useState(false); // edit mode
        const [loading, setLoading] = useState(false);
        const [templateLoading, setTemplateLoading] = useState(false);
        const generation = useRef(0);
        const assistantDraft = useRef<AssistantTemplateDraft>({});
        const submitting = useRef(false);
        const { t } = useTranslation('flow');
        const { appConfig } = useContext(locationContext);
        const securityRef = useRef<any>(null);

        const [appId, setAppId] = useState<string>('');
        const [errors, setErrors] = useState<any>({});

        useImperativeHandle(ref, () => ({
            open(type: AppType, tempId?: number) {
                ++generation.current;
                assistantDraft.current = {};
                submitting.current = false;
                setLoading(false);
                tempDataRef.current = null;
                setTemplateLoading(false);
                setType(type);
                setIsEditMode(false);
                setFormData({
                    url: '',
                    name: '',
                    desc: '',
                });
                if (tempId) {
                    void handleSelectTemplate(type, tempId);
                }
                setErrors({});
                setOpen(true);
                setAppId('');
            },
            edit(type: AppType, flow: any) {
                ++generation.current;
                assistantDraft.current = {};
                setType(type);
                setIsEditMode(true);
                fetchDetails(type, flow);
                setErrors({});
                setOpen(true);
                tempDataRef.current = null;
                setAppId(flow.id);
            },
        }));

        const tempDataRef = useRef<any>(null);
        useEffect(() => {
            const reset = () => {
                ++generation.current;
                tempDataRef.current = null;
                assistantDraft.current = {};
                submitting.current = false;
                setOpen(false);
                setLoading(false);
                setTemplateLoading(false);
            };
            window.addEventListener('bisheng:management-scope-changed', reset);
            const invalidate = () => { ++generation.current; };
            return () => {
                invalidate();
                window.removeEventListener('bisheng:management-scope-changed', reset);
            };
        }, []);

        const handleSelectTemplate = async (type: AppType, tempId: number) => {
            const request = generation.current;
            setTemplateLoading(true);
            try {
                const [template] = await readTempsDatabase(type, tempId);
                if (request !== generation.current) return;
                tempDataRef.current = JSON.parse(JSON.stringify(template));
                setFormData({ url: template.logo || '', name: `${template.name}-${generateUUID(5)}`, desc: template.description || '' });
            } catch (error) {
                if (request === generation.current) { setOpen(false); showApiError(error); }
            } finally {
                if (request === generation.current) setTemplateLoading(false);
            }
        }

        const fetchDetails = async (type: AppType, flow: any) => {
            setFormData({
                url: flow.logo,
                name: flow.name,
                desc: flow.description,
            });
        };

        const validateField = (name: string, value: string) => {
            switch (name) {
                case 'name':
                    if (value.length > 50) return AppType.ASSISTANT === appType ? t('maxNameLengthAssistant') : t('maxNameLengthWorkflow');
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
            if (templateLoading || submitting.current) return;
        if ((String((formData.name) ?? '').length > 50) || (String((formData.desc) ?? '').length > 1000)) return;

            e.preventDefault();
            const isValid = validateForm();
            if (!isValid) return;

            setLoading(true);
            submitting.current = true;
            const request = generation.current;
            try {
            if (isEditMode) {
                await onSave({
                    name: formData.name,
                    description: formData.desc,
                    logo: formData.url,
                    viewUrl: formData.viewUrl,
                })
                setOpen(false);
                return;
            }

            const template = tempDataRef.current ? JSON.parse(JSON.stringify(tempDataRef.current)) : null;
            if (template) {
                if (AppType.ASSISTANT === appType) {
                    const id = await instantiateAssistantTemplate(template.data, formData, assistantDraft.current);
                    if (request === generation.current) { setOpen(false); navigate('/assistant/' + id); }
                    return;
                }
                if (AppType.FLOW === appType) {
                    for (let i = 0; i < template.data.nodes.length; i++) {
                        const node = template.data.nodes[i];
                        await copyReportTemplate(node.data)
                        if (request !== generation.current) return;
                    }

                    const [workflow, assistant] = await Promise.all([getLlmDefaultModel(), getAssistantModelConfig()])
                    const workflowModelId = workflow.model_id;
                    const assistantModelId = assistant.llm_list.find(item => item.default)?.model_id;
                    if (request !== generation.current) return;
                    delete template.data.source;

                    template.data.nodes.forEach(node => {
                        if (['rag', 'llm', 'agent', 'qa_retriever'].includes(node.data.type)) {
                            node.data.group_params.forEach(group =>
                                group.params.forEach(param => {
                                    if (param.type === 'bisheng_model') {
                                        param.value = workflowModelId;
                                    } else if (param.type === 'agent_model') {
                                        param.value = assistantModelId;
                                    } else if (param.type === 'knowledge_select_multi' && param.value.type !== 'tmp') {
                                        param.value.value = [];
                                    } else if (param.type === 'qa_select_multi') {
                                        param.value = [];
                                    } else if (param.type === 'add_tool') {
                                        param.value = [];
                                    }
                                })
                            )
                        }
                    })
                    const res = await createWorkflowApi(formData.name, formData.desc, formData.url, template);
                    if (res && request === generation.current) navigate('/flow/' + res.id);
                }
            } else {
                if (appType === AppType.ASSISTANT) {
                    const res = await createAssistantsApi(formData.name, formData.desc, formData.url);
                    if (res) {
                        //@ts-ignore
                        window.assistantCreate = true // Mark the created assistant
                        navigate('/assistant/' + res.id)
                    }
                } else {
                    if (appId) return navigate('/flow/' + appId);
                    const workflow = await createWorkflowApi(formData.name, formData.desc, formData.url);
                    if (workflow) {
                        const navigateToFlow = (id) => navigate(`/flow/${id}`);
                        if (!appConfig.isPro) return navigateToFlow(workflow.id);

                        setAppId(workflow.id);
                        const securityCreated = await securityRef.current.create(workflow.id);
                        if (securityCreated) navigateToFlow(workflow.id);
                    }
                }
            }
            } catch (error) {
                showApiError(error);
            } finally {
                if (request === generation.current) {
                    submitting.current = false;
                    setLoading(false);
                }
            }
        };

        const uploadAvator = (file: File) => {
            uploadFileWithProgress(file, (progress) => { }, 'icon').then(res => {
                setFormData(prev => ({ ...prev, url: res.relative_path, viewUrl: res.file_path }));
            });
        };

        const previewAvatar = useMemo(() =>
            formData.url ? __APP_ENV__.BASE_URL + (formData.viewUrl || formData.url) : '',
            [formData.url, formData.viewUrl]);

        return (
            <Dialog open={open} onOpenChange={(value) => { if (!value) ++generation.current; setOpen(value); }}>
                <DialogContent className="sm:max-w-[625px] bg-background-login">
                    <DialogHeader>
                        <DialogTitle>{isEditMode ? t('edit') : t('create')}{appType === AppType.ASSISTANT ? t('assistant') : t('workflow')}</DialogTitle>
                    </DialogHeader>
                    <div className="flex flex-col mt-2">
                        <div className="mb-6">
                            <label htmlFor="name" className="bisheng-label">
                                {appType === AppType.ASSISTANT ? t('assistantAvatar') : t('workflowAvatar')}
                            </label>
                            <Avator value={previewAvatar} className="mt-3" onChange={uploadAvator}>
                                <AppAvator id={6} flowType={AppTypeToNum[appType]} className="size-8"></AppAvator>
                            </Avator>
                        </div>
                        <div className="mb-6">
                            <label htmlFor="name" className="bisheng-label">
                                {appType === AppType.ASSISTANT ? t('build_assistantName') : t('name')}
                                <span className="bisheng-tip">*</span>
                            </label>
                            <Input id="name" name="name" maxLength={50} showCount placeholder={appType === AppType.ASSISTANT ? t('giveAssistantAName') : t('giveWorkflowAName')} value={formData.name} onChange={handleChange} className={"mt-3"} />
                            {errors.name && <p className="bisheng-tip mt-1">{errors.name}</p>}
                        </div>
                        <div className="mb-6">
                            <label htmlFor="desc" className="bisheng-label">
                                {appType === AppType.ASSISTANT ? t('build_roleAndTasks') : t('description')}
                            </label>
                            <Textarea id="desc" name="desc" placeholder={appType === AppType.ASSISTANT ? assistantRoleExample() : t('enterWorkflowDescription')} maxLength={1000} value={formData.desc} onChange={handleChange} textareaClassName={"mt-3 min-h-32 pt-3"} showCount />
                            {errors.desc && <p className="bisheng-tip mt-1">{errors.desc}</p>}
                        </div>
                    </div>
                    {/* Workflow Security Review */}
                    <div className={isEditMode ? '' : 'hidden'}>
                        {appConfig.isPro && <Accordion type="multiple" className="w-full">
                            <AssistantSetting ref={securityRef} id={appId} type={5} />
                        </Accordion>}
                    </div>
                    <DialogFooter>
                        <DialogClose>
                            <Button variant="outlined" type="button" onClick={() => setFormData({ name: '', desc: '', url: '' })} color="default">
                                {t('cancel')}
                            </Button>
                        </DialogClose>
                        <Button disabled={((String((formData.name) ?? '').length > 50) || (String((formData.desc) ?? '').length > 1000)) || (!formData.name || loading || templateLoading)} type="submit" onClick={handleSubmit}>
                            {(loading || templateLoading) && <Outlined.Loading className="animate-spin mr-2" />}
                            {t(isEditMode ? 'save' : 'create')}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        );
    });

export default CreateApp;
