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
import { getKnowledgeConfigApi, getAppConfig, setKnowledgeConfigApi } from "@/controllers/API";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { NonNegativeInput, Textarea, Input } from "@/components/bs-ui/input";
import { canManageWorkbenchConfig, isGlobalSuperUser } from "@/pages/ModelPage/manage/permissions";
import Preview from "./Preview";
import { resolveConfigString } from "./configValue";
import { useContext, useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { DepartmentKnowledgeSpaceManagerDialog } from "./DepartmentKnowledgeSpaceManagerDialog";
import ConfigInheritanceBanner, { resolveConfigEnvelope } from "./ConfigInheritanceBanner";
import {
    KnowledgeSpaceSensitivePolicy,
    type KnowledgeSpaceSensitivePolicyHandle,
} from "./KnowledgeSpaceSensitivePolicy";
import KnowledgeSpaceTagSection from "./KnowledgeSpaceTagLibrarySection";
import KnowledgeSpaceReviewTagSection from "./KnowledgeSpaceReviewTagSection";

interface KnowledgeConfigForm {
    /** 系统提示词，对应接口 system_prompt */
    systemPrompt: string;
    /** 用户提示词，对应接口 user_prompt */
    userPrompt: string;
    /** 知识空间检索结果最大字符数，对应接口 max_chunk_size */
    maxChunkSize: number;
    /** 租户级"自动生成标签"功能可见性，对应接口 auto_tag_visible */
    autoTagVisible: boolean;
    /** 租户级"待审核标签"功能可见性，对应接口 review_tag_visible */
    reviewTagVisible: boolean;
    /** 租户级待审核标签相似度阈值；空字符串表示使用系统默认值 */
    reviewTagSimilarityThreshold: string;
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
        systemSimilarityThreshold,
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

                            <KnowledgeSpaceTagSection
                                visible={formData.autoTagVisible}
                                onToggle={(checked) =>
                                    setFormData((prev) => ({ ...prev, autoTagVisible: checked }))
                                }
                            />

                            <KnowledgeSpaceReviewTagSection
                                visible={formData.reviewTagVisible}
                                onToggle={(checked) =>
                                    setFormData((prev) => ({ ...prev, reviewTagVisible: checked }))
                                }
                            />

                            {formData.reviewTagVisible && (
                                <div className="p-5 rounded-lg">
                                    <div className="border-t border-[#ECECEC] pt-6">
                                        <Label className="bisheng-label">
                                            {t("build.reviewTagSimilarityThreshold", "标签相似度阈值")}
                                        </Label>
                                        <p className="mt-1 text-sm text-[#86909C]">
                                            {t(
                                                "build.reviewTagSimilarityThresholdDesc",
                                                "用于待审核标签入库与 AI 打标时的模糊匹配；留空则使用系统默认值 {{threshold}}。",
                                                { threshold: systemSimilarityThreshold },
                                            )}
                                        </p>
                                        <div className="mt-3 flex items-center max-w-40">
                                            <Input
                                                type="number"
                                                min={0}
                                                max={1}
                                                step={0.01}
                                                value={formData.reviewTagSimilarityThreshold}
                                                placeholder={systemSimilarityThreshold}
                                                onChange={(e) =>
                                                    setFormData((prev) => ({
                                                        ...prev,
                                                        reviewTagSimilarityThreshold: e.target.value,
                                                    }))
                                                }
                                            />
                                        </div>
                                    </div>
                                </div>
                            )}

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
function applyKnowledgeConfigResponse(
    res: unknown,
    t: TFunction,
    setFormData: Dispatch<SetStateAction<KnowledgeConfigForm>>,
    setConfigMeta: Dispatch<SetStateAction<any>>,
) {
    const { data: envData, meta } = resolveConfigEnvelope<Record<string, unknown>>(res);
    setConfigMeta(meta);
    const cfg = envData != null && typeof envData === "object" ? envData : null;
    const systemPromptFromRes = cfg?.system_prompt ?? cfg?.systemPrompt;
    const userPromptFromRes = cfg?.user_prompt ?? cfg?.userPrompt;
    const maxChunkSizeFromRes = cfg?.max_chunk_size ?? cfg?.maxTokens;
    const autoTagVisibleFromRes = cfg?.auto_tag_visible ?? cfg?.autoTagVisible;
    const reviewTagVisibleFromRes = cfg?.review_tag_visible ?? cfg?.reviewTagVisible;
    const reviewTagSimilarityThresholdFromRes =
        cfg?.review_tag_similarity_threshold ?? cfg?.reviewTagSimilarityThreshold;
    const resolvedSystemPrompt = resolveConfigString(systemPromptFromRes, "");
    const resolvedUserPrompt = resolveConfigString(userPromptFromRes, "");
    setFormData((prev) => ({
        ...prev,
        systemPrompt: resolvedSystemPrompt || t("chatConfig.aiPrompt"),
        userPrompt: resolvedUserPrompt || t("chatConfig.retrievedAndQuestion"),
        maxChunkSize: typeof maxChunkSizeFromRes === "number" ? maxChunkSizeFromRes : prev.maxChunkSize,
        autoTagVisible: Boolean(autoTagVisibleFromRes),
        reviewTagVisible: Boolean(reviewTagVisibleFromRes),
        reviewTagSimilarityThreshold:
            reviewTagSimilarityThresholdFromRes == null || reviewTagSimilarityThresholdFromRes === ""
                ? ""
                : String(reviewTagSimilarityThresholdFromRes),
    }));
}

const useKnowledgeConfig = (scopeVersion = 0) => {
    const { t } = useTranslation();
    const [formData, setFormData] = useState<KnowledgeConfigForm>({
        systemPrompt: '',
        userPrompt: '',
        maxChunkSize: 15000,
        autoTagVisible: false,
        reviewTagVisible: false,
        reviewTagSimilarityThreshold: "",
    });
    const [systemSimilarityThreshold, setSystemSimilarityThreshold] = useState("0.85");

    const [errors, setErrors] = useState<{ systemPrompt: string; userPrompt: string }>({
        systemPrompt: '',
        userPrompt: '',
    });
    const [configMeta, setConfigMeta] = useState<any>(null);

    // 初始化时从后台读取配置
    useEffect(() => {
        setConfigMeta(null);
        getAppConfig().then((env: any) => {
            const threshold = env?.knowledges?.tag_library?.review_tag_similarity_threshold;
            if (typeof threshold === "number") {
                setSystemSimilarityThreshold(String(threshold));
            }
        });
        getKnowledgeConfigApi().then((res) => {
            applyKnowledgeConfigResponse(res, t, setFormData, setConfigMeta);
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

        const parsedReviewTagSimilarityThreshold = (() => {
            const raw = (formData.reviewTagSimilarityThreshold || "").trim();
            if (!raw) return null;
            const value = Number(raw);
            if (!Number.isFinite(value) || value < 0 || value > 1) {
                toast({
                    variant: "error",
                    description: t("build.reviewTagSimilarityThresholdInvalid", "相似度阈值必须为 0 到 1 之间的数字"),
                });
                return undefined;
            }
            return value;
        })();
        if (parsedReviewTagSimilarityThreshold === undefined) {
            return false;
        }

        const dataToSave = {
            system_prompt: finalSystemPrompt,
            user_prompt: finalUserPrompt,
            max_chunk_size: formData.maxChunkSize,
            auto_tag_visible: formData.autoTagVisible,
            review_tag_visible: formData.reviewTagVisible,
            review_tag_similarity_threshold: parsedReviewTagSimilarityThreshold,
        };

        const res = await captureAndAlertRequestErrorHoc(setKnowledgeConfigApi(dataToSave));
        if (res) {
            const reloaded = await captureAndAlertRequestErrorHoc(getKnowledgeConfigApi());
            if (reloaded) {
                applyKnowledgeConfigResponse(reloaded, t, setFormData, setConfigMeta);
            } else {
                setConfigMeta({
                    inherited_from_root: false,
                    has_override: true,
                });
            }
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
        systemSimilarityThreshold,
        handleSave,
    };
};
