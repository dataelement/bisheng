// src/features/chat-config/ChatConfig.tsx
import { Button } from "@/components/bs-ui/button";
import { CardContent } from "@/components/bs-ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { Input, NonNegativeInput, Textarea } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import { locationContext } from "@/contexts/locationContext";
import { userContext } from "@/contexts/userContext";
import { getSubConfigApi, setSubConfigApi } from "@/controllers/API";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { useContext, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import WebSearchForm from "../tools/builtInTool/WebSearchFrom";
import { resolveConfigString } from "./configValue";
import Preview from "./Preview";


export interface FormErrors {
    sidebarSlogan: string;
    welcomeMessage: string;
    functionDescription: string;
    inputPlaceholder: string;
    modelNames: string[] | string[][];
    webSearch?: Record<string, string>;
    systemPrompt: string;
    userPrompt: string;
    feedbackTips: string;
    model: string;
    kownledgeBase: string;
    applicationCenterWelcomeMessage: string;
    applicationCenterDescription: string;
}

export interface ChatConfigForm {
    systemPrompt: string;
    userPrompt: string;
    maxChunkSize: number;
    feedbackTips: string;
}
export default function Subscribe() {
    const sidebarSloganRef = useRef<HTMLDivElement>(null);
    const welcomeMessageRef = useRef<HTMLDivElement>(null);
    const functionDescriptionRef = useRef<HTMLDivElement>(null);
    const inputPlaceholderRef = useRef<HTMLDivElement>(null);
    const knowledgeBaseRef = useRef<HTMLDivElement>(null);
    const modelRefs = useRef<(HTMLDivElement | null)[]>([]);
    const webSearchRef = useRef<HTMLDivElement>(null);
    const systemPromptRef = useRef<HTMLDivElement>(null);
    const appCenterWelcomeRef = useRef<HTMLDivElement>(null);
    const appCenterDescriptionRef = useRef<HTMLDivElement>(null);
    const modelManagementContainerRef = useRef<HTMLDivElement>(null);

    const { t } = useTranslation()
    const {
        formData,
        errors,
        setErrors,
        setFormData,
        handleInputChange,
        toggleFeature,
        handleSave
    } = useChatConfig({
        sidebarSloganRef,
        welcomeMessageRef,
        functionDescriptionRef,
        inputPlaceholderRef,
        knowledgeBaseRef,
        modelRefs,
        webSearchRef,
        systemPromptRef,
        appCenterWelcomeRef,
        appCenterDescriptionRef,
        modelManagementContainerRef,
    });


    const [webSearchDialogOpen, setWebSearchDialogOpen] = useState(false);
    const { user } = useContext(userContext);
    const navigate = useNavigate()
    useEffect(() => {
        if (user.user_id && user.role !== 'admin') {
            navigate('/build/apps')
        }
    }, [user])
    return (
        <div className=" h-full overflow-y-scroll scrollbar-hide relative border-t">
            <div className="pt-4 relative">
                <CardContent className="pt-4 relative">
                    <div className="w-full  max-h-[calc(100vh-180px)] overflow-y-scroll scrollbar-hide">
                        <div className="mb-6">
                            <div className="flex items-center mb-2">
                                <p className="text-lg font-bold flex items-center">
                                    <span>{t("chatConfig.prompts")}</span>
                                </p>
                            </div>
                            <>
                                <Label className="bisheng-label">{t('chatConfig.sysPrompts')}</Label>
                                <div className="mt-3">
                                    <Textarea
                                        value={formData.systemPrompt}
                                        placeholder={t('chatConfig.aiPrompt')}
                                        className="min-h-48"
                                        maxLength={30000}
                                        onChange={(e) => {
                                            const val = e.target.value;
                                            setFormData(prev => ({ ...prev, systemPrompt: val }));
                                            setErrors(prev => ({
                                                ...prev,
                                                systemPrompt: val.length >= 30000
                                                    ? t('chatConfig.errors.maxCharacters', { count: 30000 })
                                                    : '',
                                            }));
                                        }}
                                    />
                                    {errors.systemPrompt && (
                                        <p className="text-xs text-red-500 mt-1">{errors.systemPrompt}</p>
                                    )}
                                </div>
                            </>
                            <>
                                <Label className="bisheng-label">{t('chatConfig.userPrompts')}</Label>
                                <div className="mt-3">
                                    <Textarea
                                        value={formData.userPrompt}
                                        placeholder={t('chatConfig.referenceAndQuestion')}
                                        className="min-h-48"
                                        maxLength={30000}
                                        onChange={(e) => {
                                            const val = e.target.value;
                                            setFormData(prev => ({ ...prev, userPrompt: val }));
                                            setErrors(prev => ({
                                                ...prev,
                                                userPrompt: val.length >= 30000
                                                    ? t('chatConfig.errors.maxCharacters', { count: 30000 })
                                                    : '',
                                            }));
                                        }}
                                    />
                                    {errors.userPrompt && (
                                        <p className="text-xs text-red-500 mt-1">{errors.userPrompt}</p>
                                    )}
                                </div>
                            </>
                            <>
                                <Label className="bisheng-label">{t('chatConfig.articleMax')}</Label>
                                <QuestionTooltip className="relative top-0.5 ml-1" content={t('chatConfig.knowledgeArticleMaxLengthTooltip')}></QuestionTooltip>
                                <div className="flex items-center max-w-40">
                                    <NonNegativeInput
                                        className="mt-3"
                                        value={formData.maxChunkSize ?? ''}
                                        defaultValue={15000}
                                        max={15000}
                                        onValueChange={(val) => {
                                            setFormData(prev => ({ ...prev, maxChunkSize: val }));
                                        }}
                                    />
                                    <span className="mt-3 ml-2">{t('chatConfig.character')}</span>
                                </div>
                            </>
                        </div>
                        <div className="mb-6">
                            <div className="flex items-center mb-2">
                                <p className="text-lg font-bold flex items-center">
                                    <span>{t('chatConfig.feedbackPrompt')}</span>
                                    <QuestionTooltip className="relative top-0.5 ml-1" content={t('chatConfig.manualCrawlRequestTooltip')}></QuestionTooltip>
                                </p>
                            </div>
                            <>
                                <div>
                                    <Input
                                        className="mt-3"
                                        value={formData.feedbackTips}
                                        onChange={(e) => {
                                            const val = e.target.value;
                                            setFormData(prev => ({ ...prev, feedbackTips: val }));
                                            setErrors(prev => ({
                                                ...prev,
                                                feedbackTips: '',
                                            }));
                                        }}
                                    />
                                    {errors.feedbackTips && (
                                        <p className="text-xs text-red-500 mt-1">{errors.feedbackTips}</p>
                                    )}
                                </div>
                            </>
                        </div>
                    </div>
                    <div className="flex justify-end gap-4 absolute bottom-1 right-4">
                        <Preview onBeforView={handleSave} />
                        <Button onClick={handleSave}>{t('save')}</Button>
                    </div>
                </CardContent>
            </div>
            <Dialog open={webSearchDialogOpen} onOpenChange={setWebSearchDialogOpen}>
                <DialogContent className="sm:max-w-[625px] bg-background-login">
                    <DialogHeader>
                        <DialogTitle>{t('chatConfig.webSearchConfig')}</DialogTitle>
                    </DialogHeader>
                    <WebSearchForm isApi={true} />
                </DialogContent>
            </Dialog>
        </div>
    );
}


interface UseChatConfigProps {
    sidebarSloganRef: React.RefObject<HTMLDivElement>;
    welcomeMessageRef: React.RefObject<HTMLDivElement>;
    functionDescriptionRef: React.RefObject<HTMLDivElement>;
    inputPlaceholderRef: React.RefObject<HTMLDivElement>;
    knowledgeBaseRef: React.RefObject<HTMLDivElement>;
    modelRefs: React.MutableRefObject<(HTMLDivElement | null)[]>;
    webSearchRef: React.RefObject<HTMLDivElement>;
    systemPromptRef: React.RefObject<HTMLDivElement>;
    appCenterWelcomeRef: React.RefObject<HTMLDivElement>;
    appCenterDescriptionRef: React.RefObject<HTMLDivElement>;
    modelManagementContainerRef: React.RefObject<HTMLDivElement>;
}

const useChatConfig = (refs: UseChatConfigProps) => {
    const { t } = useTranslation()

    const [formData, setFormData] = useState<ChatConfigForm>({
        systemPrompt: '',
        userPrompt: '',
        maxChunkSize: 15000,
        feedbackTips: '请将您的网站爬取需求发送至邮箱：XXXX@XX',
    });

    useEffect(() => {
        getSubConfigApi().then((res) => {
            // Interceptor returns response.data.data — null when no config row exists yet.
            const cfg = res != null && typeof res === 'object' ? (res as Record<string, unknown>) : null;
            setFormData((prev) => {
                const systemPromptFromRes = cfg?.systemPrompt ?? cfg?.system_prompt;
                const userPromptFromRes = cfg?.userPrompt ?? cfg?.user_prompt;
                const maxChunkSizeFromRes = cfg?.max_chunk_size ?? cfg?.maxTokens;
                const feedbackTipsFromRes = cfg?.feedback_tips ?? cfg?.feedbackTips;
                return {
                    ...prev,
                    systemPrompt: resolveConfigString(systemPromptFromRes, prev.systemPrompt),
                    userPrompt: resolveConfigString(userPromptFromRes, prev.userPrompt),
                    maxChunkSize: typeof maxChunkSizeFromRes === 'number' ? maxChunkSizeFromRes : prev.maxChunkSize,
                    feedbackTips: resolveConfigString(feedbackTipsFromRes, prev.feedbackTips),
                };
            });
        });
    }, []);

    const [errors, setErrors] = useState<FormErrors>({
        sidebarSlogan: '',
        welcomeMessage: '',
        functionDescription: '',
        inputPlaceholder: '',
        kownledgeBase: '',
        model: '',
        modelNames: [],
        webSearch: undefined,
        systemPrompt: '',
        userPrompt: '',
        feedbackTips: '',
        applicationCenterWelcomeMessage: '',
        applicationCenterDescription: '',
    });

    const handleInputChange = (field: keyof ChatConfigForm, value: string, maxLength: number) => {
        setFormData(prev => ({ ...prev, [field]: value }));
        if (value.length >= maxLength) {
            setErrors(prev => ({ ...prev, [field]: t('chatConfig.errors.maxCharacters', { count: maxLength }) }));
        } else {
            setErrors(prev => ({ ...prev, [field]: '' }));
        }
    };

    const toggleFeature = (feature: keyof ChatConfigForm, enabled: boolean) => {

        return;
    };

    const { toast } = useToast()
    const { reloadConfig } = useContext(locationContext)
    const validateForm = (): boolean => {
        let isValid = true;
        const newErrors: FormErrors = {
            sidebarSlogan: '',
            welcomeMessage: '',
            functionDescription: '',
            inputPlaceholder: '',
            kownledgeBase: '',
            model: '',
            modelNames: [],
            webSearch: undefined,
            systemPrompt: '',
            userPrompt: '',
            feedbackTips: '',
            applicationCenterWelcomeMessage: '',
            applicationCenterDescription: '',
        };

        const sys = (formData.systemPrompt || '').trim();
        if (!sys) {
            newErrors.systemPrompt = '不可为空';
            isValid = false;
        } else if (sys.length > 30000) {
            newErrors.systemPrompt = t('chatConfig.errors.maxCharacters', { count: 30000 });
            isValid = false;
        }

        const user = (formData.userPrompt || '').trim();
        if (!user) {
            newErrors.userPrompt = '不可为空';
            isValid = false;
        } else if (user.length > 30000) {
            newErrors.userPrompt = t('chatConfig.errors.maxCharacters', { count: 30000 });
            isValid = false;
        }

        const feedback = (formData.feedbackTips || '').trim();
        if (!feedback) {
            newErrors.feedbackTips = '请输入需求反馈提示文案';
            isValid = false;
        }

        setErrors(newErrors);
        return isValid;
    };

    const handleSave = async () => {
        if (!validateForm()) {
            // 主要针对提示词为空的场景，给出明确的 toast
            const sys = (formData.systemPrompt || '').trim();
            const user = (formData.userPrompt || '').trim();
            const feedback = (formData.feedbackTips || '').trim();
            if (!sys) {
                toast({
                    variant: 'error',
                    description: '系统提示词不可为空',
                });
                return false;
            }
            if (!user) {
                toast({
                    variant: 'error',
                    description: '用户提示词不可为空',
                });
                return false;
            }
            if (!feedback) {
                toast({
                    variant: 'error',
                    description: '请输入需求反馈提示文案',
                });
            }
            return false;
        }
        const feedback = (formData.feedbackTips || '').trim();
        const feedbackTooLong = feedback.length > 1000;
        const dataToSave = {
            system_prompt: formData.systemPrompt,
            user_prompt: formData.userPrompt,
            max_chunk_size: formData.maxChunkSize,
            feedback_tips: formData.feedbackTips,
        };

        captureAndAlertRequestErrorHoc(setSubConfigApi(dataToSave)).then((res) => {
            if (res) {
                if (feedbackTooLong) {
                    toast({
                        variant: 'warning',
                        description: '提示文案不可超过 1000 个字符',
                    });
                } else {
                    toast({
                        variant: 'success',
                        description: t('chatConfig.saveSuccess'),
                    });
                }
                reloadConfig()
            }
        })

        return true
    };

    return {
        formData,
        errors,
        setFormData,
        setErrors,
        handleInputChange,
        toggleFeature,
        handleSave
    };
};
