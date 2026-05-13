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
import { canManageModelSettings } from "@/pages/ModelPage/manage/permissions";
import { useContext, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import WebSearchForm from "../tools/builtInTool/WebSearchFrom";
import { resolveConfigString } from "./configValue";
import Preview from "./Preview";
import ConfigInheritanceBanner, { resolveConfigEnvelope } from "./ConfigInheritanceBanner";
import { SubscriptionSensitivePolicy } from "./SubscriptionSensitivePolicy";


export interface FormErrors {
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
export default function Subscribe({ scopeVersion = 0 }: { scopeVersion?: number }) {
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
        configMeta,
        handleInputChange,
        toggleFeature,
        handleSave
    } = useChatConfig({
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
    }, scopeVersion);


    const [webSearchDialogOpen, setWebSearchDialogOpen] = useState(false);
    const { user } = useContext(userContext);
    const navigate = useNavigate()
    useEffect(() => {
        if (user.user_id && !canManageModelSettings(user)) {
            navigate('/build/apps')
        }
    }, [navigate, user])
    return (
        <div className=" h-full overflow-y-scroll scrollbar-hide relative border-t">
            <div className="pt-4 relative">
                <CardContent className="pt-4 relative">
                    <div className="w-full  max-h-[calc(100vh-180px)] overflow-y-scroll scrollbar-hide">
                        <ConfigInheritanceBanner meta={configMeta} />
                        <SubscriptionSensitivePolicy />
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

const useChatConfig = (refs: UseChatConfigProps, scopeVersion = 0) => {
    const { t } = useTranslation()

    const [formData, setFormData] = useState<ChatConfigForm>({
        systemPrompt: '',
        userPrompt: '',
        maxChunkSize: 15000,
        feedbackTips: '请将您的网站爬取需求发送至邮箱：XXXX@XX',
    });
    const [configMeta, setConfigMeta] = useState<any>(null);

    useEffect(() => {
        setConfigMeta(null);
        getSubConfigApi().then((res) => {
            const { data: envData, meta } = resolveConfigEnvelope<Record<string, unknown>>(res);
            setConfigMeta(meta);
            const cfg = envData != null && typeof envData === 'object' ? envData : null;
            setFormData((prev) => {
                const systemPromptFromRes = cfg?.systemPrompt ?? cfg?.system_prompt;
                const userPromptFromRes = cfg?.userPrompt ?? cfg?.user_prompt;
                const maxChunkSizeFromRes = cfg?.max_chunk_size ?? cfg?.maxTokens;
                const feedbackTipsFromRes = cfg?.feedback_tips ?? cfg?.feedbackTips;
                // When backend returns no saved value, seed the textarea with the
                // localized default template so it is editable as a real value.
                const resolvedSystemPrompt = resolveConfigString(systemPromptFromRes, '');
                const resolvedUserPrompt = resolveConfigString(userPromptFromRes, '');
                return {
                    ...prev,
                    systemPrompt: resolvedSystemPrompt || t('chatConfig.aiPrompt'),
                    userPrompt: resolvedUserPrompt || t('chatConfig.referenceAndQuestion'),
                    maxChunkSize: typeof maxChunkSizeFromRes === 'number' ? maxChunkSizeFromRes : prev.maxChunkSize,
                    feedbackTips: resolveConfigString(feedbackTipsFromRes, prev.feedbackTips),
                };
            });
        });
    }, [scopeVersion, t]);

    const [errors, setErrors] = useState<FormErrors>({
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

        // systemPrompt / userPrompt are auto-refilled with the i18n default template
        // in handleSave when blank, so only the length cap needs to be checked here.
        const sys = (formData.systemPrompt || '').trim();
        if (sys.length > 30000) {
            newErrors.systemPrompt = t('chatConfig.errors.maxCharacters', { count: 30000 });
            isValid = false;
        }

        const user = (formData.userPrompt || '').trim();
        if (user.length > 30000) {
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
        // Refill blank prompts with the i18n default template so the empty input
        // never reaches the server; reflect the refill in formData for the UI too.
        const finalSystemPrompt = (formData.systemPrompt || '').trim() || t('chatConfig.aiPrompt');
        const finalUserPrompt = (formData.userPrompt || '').trim() || t('chatConfig.referenceAndQuestion');
        if (finalSystemPrompt !== formData.systemPrompt || finalUserPrompt !== formData.userPrompt) {
            setFormData(prev => ({
                ...prev,
                systemPrompt: finalSystemPrompt,
                userPrompt: finalUserPrompt,
            }));
        }

        if (!validateForm()) {
            const feedback = (formData.feedbackTips || '').trim();
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
            system_prompt: finalSystemPrompt,
            user_prompt: finalUserPrompt,
            max_chunk_size: formData.maxChunkSize,
            feedback_tips: formData.feedbackTips,
        };

        captureAndAlertRequestErrorHoc(setSubConfigApi(dataToSave)).then((res) => {
            if (res) {
                setConfigMeta({
                    inherited_from_root: false,
                    has_override: true,
                });
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
        configMeta,
        handleInputChange,
        toggleFeature,
        handleSave
    };
};
