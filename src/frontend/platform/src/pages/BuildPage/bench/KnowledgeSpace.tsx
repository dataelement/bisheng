// 工作台「知识空间」配置页：只保留系统提示词、用户提示词、知识空间检索结果最大字符数
import { Button } from "@/components/bs-ui/button";
import { CardContent } from "@/components/bs-ui/card";
import { Label } from "@/components/bs-ui/label";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { locationContext } from "@/contexts/locationContext";
import { userContext } from "@/contexts/userContext";
import { getKnowledgeConfigApi, setKnowledgeConfigApi } from "@/controllers/API";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { Input, NonNegativeInput, Textarea } from "@/components/bs-ui/input";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import Preview from "./Preview";
import { useContext, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

interface KnowledgeConfigForm {
    /** 系统提示词，对应接口 system_prompt */
    systemPrompt: string;
    /** 用户提示词，对应接口 user_prompt */
    userPrompt: string;
    /** 知识空间检索结果最大字符数，对应接口 max_chunk_size */
    maxChunkSize: number;
}

export default function KnowledgeSpace() {
    const { t } = useTranslation();
    const { formData, setFormData, errors, setErrors, handleSave } = useKnowledgeConfig();
    const { user } = useContext(userContext);
    const navigate = useNavigate();

    // 非 admin 角色跳回应用列表
    useEffect(() => {
        if (user.user_id && user.role !== 'admin') {
            navigate('/build/apps');
        }
    }, [user, navigate]);

    return (
        <div className="h-full overflow-y-scroll scrollbar-hide relative border-t">
            <div className="pt-4 relative">
                <CardContent className="pt-4 relative">
                    <div className="w-full max-h-[calc(100vh-180px)] overflow-y-scroll scrollbar-hide">
                        <div className="mb-6">
                            <div className="flex items-center mb-2">
                                <p className="text-lg font-bold flex items-center">
                                    <span>{t("chatConfig.prompts")}</span>
                                </p>
                            </div>
                            {/* 系统提示词 */}
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
                            {/* 用户提示词 */}
                            <>
                                <Label className="bisheng-label">{t('chatConfig.userPrompts')}</Label>
                                <div className="mt-3">
                                    <Textarea
                                        value={formData.userPrompt}
                                        placeholder={t('chatConfig.retrievedAndQuestion')}
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
                            {/* 知识空间检索结果最大字符数 */}
                            <>
                                <Label className="bisheng-label">{t('chatConfig.knowledgeSpaceMaxChars')}</Label>
                                <div className="flex items-center max-w-40">
                                    <NonNegativeInput
                                        className="mt-3"
                                        value={formData.maxChunkSize ?? ''}
                                        defaultValue={15000}
                                        // max={15000}
                                        onValueChange={(val) => {
                                            setFormData(prev => ({ ...prev, maxChunkSize: val }));
                                        }}
                                    />
                                    <span className="mt-3 ml-2">{t('chatConfig.character')}</span>
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
        </div>
    );
}

// 只负责加载/保存系统提示词、用户提示词、max_chunk_size 的 hook
const useKnowledgeConfig = () => {
    const { t } = useTranslation();
    const [formData, setFormData] = useState<KnowledgeConfigForm>({
        systemPrompt: t('chatConfig.systemPrompt2'),
        userPrompt: t('chatConfig.retrievedAndQuestion'),
        maxChunkSize: 15000,
    });

    const [errors, setErrors] = useState<{ systemPrompt: string; userPrompt: string }>({
        systemPrompt: '',
        userPrompt: '',
    });

    // 初始化时从后台读取配置
    useEffect(() => {
        getKnowledgeConfigApi().then((res) => {
            // Interceptor returns response.data.data — null when no config row exists yet.
            const cfg = res != null && typeof res === 'object' ? (res as Record<string, unknown>) : null;
            const systemPromptFromRes = cfg?.system_prompt ?? cfg?.systemPrompt;
            const userPromptFromRes = cfg?.user_prompt ?? cfg?.userPrompt;
            const maxChunkSizeFromRes = cfg?.max_chunk_size ?? cfg?.maxTokens;
            const defaultUser = t('chatConfig.retrievedAndQuestion');
            const normalizeNonEmptyString = (value: unknown): string | undefined => {
                if (typeof value !== 'string') return undefined;
                const trimmed = value.trim();
                // Treat empty string / whitespace-only as "API empty" and do not override defaults.
                return trimmed ? value : undefined;
            };
            setFormData((prev) => ({
                ...prev,
                systemPrompt: normalizeNonEmptyString(systemPromptFromRes) ?? t('chatConfig.systemPrompt2'),
                userPrompt: normalizeNonEmptyString(userPromptFromRes) ?? defaultUser,
                maxChunkSize: typeof maxChunkSizeFromRes === 'number' ? maxChunkSizeFromRes : prev.maxChunkSize,
            }));
        });
    }, []);

    const { toast } = useToast();
    const { reloadConfig } = useContext(locationContext);

    const handleSave = async () => {
        // 校验系统提示词 & 用户提示词：不能为空且不超过 30000 字
        let isValid = true;
        const nextErrors = { systemPrompt: '', userPrompt: '' };

        const sys = (formData.systemPrompt || '').trim();
        if (!sys) {
            nextErrors.systemPrompt = t('chatConfig.errors.required');
            isValid = false;
        } else if (sys.length > 30000) {
            nextErrors.systemPrompt = t('chatConfig.errors.maxCharacters', { count: 30000 });
            isValid = false;
        }

        const user = (formData.userPrompt || '').trim();
        if (!user) {
            nextErrors.userPrompt = t('chatConfig.errors.required');
            isValid = false;
        } else if (user.length > 30000) {
            nextErrors.userPrompt = t('chatConfig.errors.maxCharacters', { count: 30000 });
            isValid = false;
        }

        setErrors(nextErrors);
        if (!isValid) {
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
            return false;
        }

        const dataToSave = {
            system_prompt: formData.systemPrompt,
            user_prompt: formData.userPrompt,
            max_chunk_size: formData.maxChunkSize,
        };

        const res = await captureAndAlertRequestErrorHoc(setKnowledgeConfigApi(dataToSave));
        if (res) {
            toast({
                variant: 'success',
                description: t('chatConfig.saveSuccess'),
            });
            reloadConfig();
        }

        return true;
    };

    return {
        formData,
        setFormData,
        errors,
        setErrors,
        handleSave,
    };
};
