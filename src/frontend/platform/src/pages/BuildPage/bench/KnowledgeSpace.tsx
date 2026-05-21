// 工作台「知识空间」配置页：只保留系统提示词、用户提示词、知识空间检索结果最大字符数
import { Button } from "@/components/bs-ui/button";
import { CardContent } from "@/components/bs-ui/card";
import { Label } from "@/components/bs-ui/label";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { locationContext } from "@/contexts/locationContext";
import {
    getDepartmentKnowledgeSpacesApi,
    type DepartmentKnowledgeSpaceSummary,
} from "@/controllers/API/departmentKnowledgeSpace";
import { userContext } from "@/contexts/userContext";
import { getKnowledgeConfigApi, setKnowledgeConfigApi } from "@/controllers/API";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { NonNegativeInput, Textarea } from "@/components/bs-ui/input";
import { canManageWorkbenchConfig, isGlobalSuperUser } from "@/pages/ModelPage/manage/permissions";
import Preview from "./Preview";
import { resolveConfigString } from "./configValue";
import { useContext, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { DepartmentKnowledgeSpaceManagerDialog } from "./DepartmentKnowledgeSpaceManagerDialog";
import ConfigInheritanceBanner, { resolveConfigEnvelope } from "./ConfigInheritanceBanner";
import {
    KnowledgeSpaceSensitivePolicy,
    type KnowledgeSpaceSensitivePolicyHandle,
} from "./KnowledgeSpaceSensitivePolicy";

interface KnowledgeConfigForm {
    /** 系统提示词，对应接口 system_prompt */
    systemPrompt: string;
    /** 用户提示词，对应接口 user_prompt */
    userPrompt: string;
    /** 知识空间检索结果最大字符数，对应接口 max_chunk_size */
    maxChunkSize: number;
}

export default function KnowledgeSpace({ scopeVersion = 0 }: { scopeVersion?: number }) {
    const { t } = useTranslation();
    const {
        formData,
        setFormData,
        errors,
        setErrors,
        handleSave: saveKnowledgeConfig,
        configMeta,
    } = useKnowledgeConfig(scopeVersion);
    const sensitivePolicyRef = useRef<KnowledgeSpaceSensitivePolicyHandle>(null);
    const [managerOpen, setManagerOpen] = useState(false);
    const [departmentSpaces, setDepartmentSpaces] = useState<DepartmentKnowledgeSpaceSummary[]>([]);
    const [departmentSpacesLoading, setDepartmentSpacesLoading] = useState(false);
    const { user } = useContext(userContext);
    const navigate = useNavigate();
    const canManageWorkbench = canManageWorkbenchConfig(user);
    const isGlobalSuper = isGlobalSuperUser(user);

    const loadDepartmentSpaces = async () => {
        setDepartmentSpacesLoading(true);
        const res = await captureAndAlertRequestErrorHoc(
            getDepartmentKnowledgeSpacesApi({ order_by: "name" }),
        );
        if (Array.isArray(res)) {
            setDepartmentSpaces(res);
        }
        setDepartmentSpacesLoading(false);
    };

    useEffect(() => {
        if (user.user_id && !canManageWorkbench) {
            navigate('/build/apps');
        }
    }, [canManageWorkbench, navigate, user.user_id]);

    useEffect(() => {
        if (user.user_id && isGlobalSuper) {
            loadDepartmentSpaces();
        }
    }, [isGlobalSuper, user.user_id]);

    const handleSave = async () => {
        const sensitiveSaved = await sensitivePolicyRef.current?.save();
        if (sensitiveSaved === false) return false;
        return saveKnowledgeConfig();
    };

    return (
        <div className="h-full overflow-y-scroll scrollbar-hide relative border-t">
            <div className="pt-4 relative">
                <CardContent className="p-0 pt-4 relative">
                    <div className="w-full max-h-[calc(100vh-180px)] overflow-y-scroll scrollbar-hide">
                        <ConfigInheritanceBanner meta={configMeta} />
                        <div className="mb-6">
                            <div className="p-5 bg-gray-50 rounded-lg">
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

                            <KnowledgeSpaceSensitivePolicy ref={sensitivePolicyRef} />

                            {isGlobalSuper && (
                                <div className="p-5 rounded-lg">
                                    <div className="mt-8 border-t border-[#ECECEC] pt-6">
                                        <div className="flex items-center justify-between gap-4">
                                            <div>
                                                <p className="text-lg font-bold">
                                                    {t("bench.departmentKnowledgeSpace", "部门知识空间")}
                                                </p>
                                                <p className="mt-1 text-sm text-[#86909C]">
                                                    {t("bench.departmentKnowledgeSpaceDesc", "统一管理部门知识空间创建，并查看已绑定部门的知识空间。")}
                                                </p>
                                            </div>
                                            <Button
                                                variant="outline"
                                                className="bg-gray-50"
                                                onClick={() => setManagerOpen(true)}
                                            >
                                                {t("bench.departmentKnowledgeSpaceManager", "部门知识空间管理")}
                                            </Button>
                                        </div>
                                        <div className="mt-5 rounded-lg border border-[#ECECEC] bg-[#FAFBFC] p-4">
                                            <div className="flex items-center justify-between gap-4">
                                                <div>
                                                    <p className="text-sm font-medium text-[#1D2129]">
                                                        {t("bench.departmentKnowledgeSpaceCreatedList", "已创建知识空间")}
                                                    </p>
                                                    <p className="mt-1 text-sm text-[#86909C]">
                                                        {t("bench.departmentKnowledgeSpaceCreatedListDesc", "已绑定部门的知识空间会统一展示在这里。")}
                                                    </p>
                                                </div>
                                                <span className="rounded bg-white px-2.5 py-1 text-xs text-[#4E5969] border border-[#E5E6EB]">
                                                    {departmentSpaces.length}
                                                </span>
                                            </div>
                                            <div className="mt-4 space-y-3">
                                                {departmentSpacesLoading ? (
                                                    <div className="rounded-lg border border-dashed border-[#D9DDE5] bg-white px-4 py-8 text-center text-sm text-[#86909C]">
                                                        {t("loading")}
                                                    </div>
                                                ) : !departmentSpaces.length ? (
                                                    <div className="rounded-lg border border-dashed border-[#D9DDE5] bg-white px-4 py-8 text-center text-sm text-[#86909C]">
                                                        {t("bench.departmentKnowledgeSpaceCreatedEmpty", "暂无已创建的部门知识空间")}
                                                    </div>
                                                ) : (
                                                    departmentSpaces.map((space) => (
                                                        <div
                                                            key={space.id}
                                                            className="rounded-lg border border-[#E5E6EB] bg-white px-4 py-3"
                                                        >
                                                            <div className="flex items-start justify-between gap-4">
                                                                <div className="min-w-0">
                                                                    <div className="flex items-center gap-2">
                                                                        <p className="truncate text-sm font-medium text-[#1D2129]">
                                                                            {space.name}
                                                                        </p>
                                                                        <span className="rounded bg-[#F2F3F5] px-2 py-0.5 text-xs text-[#4E5969]">
                                                                            {space.department_name || "--"}
                                                                        </span>
                                                                    </div>
                                                                    <p className="mt-2 text-xs text-[#86909C]">
                                                                        {t("bench.departmentKnowledgeSpaceDepartmentLabel", "所属部门")}：{space.department_name || "--"}
                                                                    </p>
                                                                </div>
                                                            </div>
                                                        </div>
                                                    ))
                                                )}
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            )}
                        </div>
                    </div>
                    <div className="flex justify-end gap-4 absolute bottom-1 right-4">
                        <Preview onBeforView={handleSave} />
                        <Button onClick={handleSave}>{t('save')}</Button>
                    </div>
                </CardContent>
            </div>

            {isGlobalSuper && (
                <>
                    <DepartmentKnowledgeSpaceManagerDialog
                        open={managerOpen}
                        onOpenChange={setManagerOpen}
                        onCreated={loadDepartmentSpaces}
                    />
                </>
            )}
        </div>
    );
}

// 只负责加载/保存系统提示词、用户提示词、max_chunk_size 的 hook
const useKnowledgeConfig = (scopeVersion = 0) => {
    const { t } = useTranslation();
    const [formData, setFormData] = useState<KnowledgeConfigForm>({
        systemPrompt: '',
        userPrompt: '',
        maxChunkSize: 15000,
    });

    const [errors, setErrors] = useState<{ systemPrompt: string; userPrompt: string }>({
        systemPrompt: '',
        userPrompt: '',
    });
    const [configMeta, setConfigMeta] = useState<any>(null);

    // 初始化时从后台读取配置
    useEffect(() => {
        setConfigMeta(null);
        getKnowledgeConfigApi().then((res) => {
            const { data: envData, meta } = resolveConfigEnvelope<Record<string, unknown>>(res);
            setConfigMeta(meta);
            const cfg = envData != null && typeof envData === 'object' ? envData : null;
            const systemPromptFromRes = cfg?.system_prompt ?? cfg?.systemPrompt;
            const userPromptFromRes = cfg?.user_prompt ?? cfg?.userPrompt;
            const maxChunkSizeFromRes = cfg?.max_chunk_size ?? cfg?.maxTokens;
            // When backend returns no saved value, seed the textarea with the
            // localized default template so it is editable as a real value.
            const resolvedSystemPrompt = resolveConfigString(systemPromptFromRes, '');
            const resolvedUserPrompt = resolveConfigString(userPromptFromRes, '');
            setFormData((prev) => ({
                ...prev,
                systemPrompt: resolvedSystemPrompt || t('chatConfig.aiPrompt'),
                userPrompt: resolvedUserPrompt || t('chatConfig.retrievedAndQuestion'),
                maxChunkSize: typeof maxChunkSizeFromRes === 'number' ? maxChunkSizeFromRes : prev.maxChunkSize,
            }));
        });
    }, [scopeVersion, t]);

    const { toast } = useToast();
    const { reloadConfig } = useContext(locationContext);

    const handleSave = async () => {
        // Refill blank prompts with the i18n default template so the empty input
        // never reaches the server; reflect the refill in formData for the UI too.
        const finalSystemPrompt = (formData.systemPrompt || '').trim() || t('chatConfig.aiPrompt');
        const finalUserPrompt = (formData.userPrompt || '').trim() || t('chatConfig.retrievedAndQuestion');
        if (finalSystemPrompt !== formData.systemPrompt || finalUserPrompt !== formData.userPrompt) {
            setFormData((prev) => ({
                ...prev,
                systemPrompt: finalSystemPrompt,
                userPrompt: finalUserPrompt,
            }));
        }

        // Length cap is the only remaining check after auto-refill removes the blank case.
        let isValid = true;
        const nextErrors = { systemPrompt: '', userPrompt: '' };

        if (finalSystemPrompt.length > 30000) {
            nextErrors.systemPrompt = t('chatConfig.errors.maxCharacters', { count: 30000 });
            isValid = false;
        }
        if (finalUserPrompt.length > 30000) {
            nextErrors.userPrompt = t('chatConfig.errors.maxCharacters', { count: 30000 });
            isValid = false;
        }

        setErrors(nextErrors);
        if (!isValid) {
            return false;
        }

        const dataToSave = {
            system_prompt: finalSystemPrompt,
            user_prompt: finalUserPrompt,
            max_chunk_size: formData.maxChunkSize,
        };

        const res = await captureAndAlertRequestErrorHoc(setKnowledgeConfigApi(dataToSave));
        if (res) {
            setConfigMeta({
                inherited_from_root: false,
                has_override: true,
            });
            toast({
                variant: 'success',
                description: t('chatConfig.saveSuccess'),
            });
            reloadConfig();
        }

        return Boolean(res);
    };

    return {
        formData,
        setFormData,
        errors,
        setErrors,
        configMeta,
        handleSave,
    };
};
