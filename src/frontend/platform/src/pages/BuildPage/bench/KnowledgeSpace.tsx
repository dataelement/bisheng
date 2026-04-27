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
import { Input, NonNegativeInput, Textarea } from "@/components/bs-ui/input";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import Preview from "./Preview";
import { resolveConfigString } from "./configValue";
import { useContext, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { DepartmentKnowledgeSpaceApprovalDialog } from "./DepartmentKnowledgeSpaceApprovalDialog";
import { DepartmentKnowledgeSpaceManagerDialog } from "./DepartmentKnowledgeSpaceManagerDialog";

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
    const [managerOpen, setManagerOpen] = useState(false);
    const [approvalTarget, setApprovalTarget] = useState<DepartmentKnowledgeSpaceSummary | null>(null);
    const [departmentSpaces, setDepartmentSpaces] = useState<DepartmentKnowledgeSpaceSummary[]>([]);
    const [departmentSpacesLoading, setDepartmentSpacesLoading] = useState(false);
    const { user } = useContext(userContext);
    const navigate = useNavigate();
    const showSensitiveCheckControl = false;

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

    // 非 admin 角色跳回应用列表
    useEffect(() => {
        if (user.user_id && user.role !== 'admin') {
            navigate('/build/apps');
        }
    }, [user, navigate]);

    useEffect(() => {
        if (user.user_id && user.role === 'admin') {
            loadDepartmentSpaces();
        }
    }, [user.user_id, user.role]);

    const handleDepartmentSpaceSettingsSaved = (
        spaceId: number,
        settings: Pick<DepartmentKnowledgeSpaceSummary, "approval_enabled" | "sensitive_check_enabled">,
    ) => {
        setDepartmentSpaces((prev) => prev.map((space) => (
            space.id === spaceId
                ? {
                    ...space,
                    approval_enabled: settings.approval_enabled,
                    sensitive_check_enabled: settings.sensitive_check_enabled,
                }
                : space
        )));
        if (approvalTarget?.id === spaceId) {
            setApprovalTarget({
                ...approvalTarget,
                approval_enabled: settings.approval_enabled,
                sensitive_check_enabled: settings.sensitive_check_enabled,
            });
        }
        void loadDepartmentSpaces();
    };

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

                            <div className="mt-6 flex justify-end gap-4">
                                <Preview onBeforView={handleSave} />
                                <Button onClick={handleSave}>{t('save')}</Button>
                            </div>

                            <div className="mt-8 border-t border-[#ECECEC] pt-6">
                                <div className="flex items-center justify-between gap-4">
                                    <div>
                                        <p className="text-lg font-bold">
                                            {t("bench.departmentKnowledgeSpace", "部门知识空间")}
                                        </p>
                                        <p className="mt-1 text-sm text-[#86909C]">
                                            {t("bench.departmentKnowledgeSpaceDesc", "统一管理部门知识空间创建，以及每个部门知识空间单独的上传审批策略。")}
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
                                                            <div className="mt-2 flex flex-wrap items-center gap-2">
                                                                <span
                                                                    className={
                                                                        space.approval_enabled
                                                                            ? "rounded bg-[#E6EDFC] px-2 py-0.5 text-xs text-[#165DFF]"
                                                                            : "rounded bg-[#F2F3F5] px-2 py-0.5 text-xs text-[#4E5969]"
                                                                    }
                                                                >
                                                                    {space.approval_enabled
                                                                        ? t("bench.departmentKnowledgeSpaceApprovalOn", "审批开启")
                                                                        : t("bench.departmentKnowledgeSpaceApprovalOff", "审批关闭")}
                                                                </span>
                                                                {showSensitiveCheckControl && (
                                                                    <span
                                                                        className={
                                                                            space.sensitive_check_enabled
                                                                                ? "rounded bg-[#FFF1F0] px-2 py-0.5 text-xs text-[#F53F3F]"
                                                                                : "rounded bg-[#F2F3F5] px-2 py-0.5 text-xs text-[#4E5969]"
                                                                        }
                                                                    >
                                                                        {space.sensitive_check_enabled
                                                                            ? t("bench.departmentKnowledgeSpaceSensitiveCheckOn", "内容安全开启")
                                                                            : t("bench.departmentKnowledgeSpaceSensitiveCheckOff", "内容安全关闭")}
                                                                    </span>
                                                                )}
                                                            </div>
                                                        </div>
                                                        <div className="flex items-center gap-2 shrink-0">
                                                            <Button
                                                                variant="outline"
                                                                className="h-7 px-3 bg-gray-50"
                                                                onClick={() => setApprovalTarget(space)}
                                                            >
                                                                {t("bench.departmentKnowledgeSpaceApprovalSettings", "审批设置")}
                                                            </Button>
                                                        </div>
                                                    </div>
                                                </div>
                                            ))
                                        )}
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </CardContent>
            </div>

            <DepartmentKnowledgeSpaceManagerDialog
                open={managerOpen}
                onOpenChange={setManagerOpen}
                onCreated={loadDepartmentSpaces}
            />
            <DepartmentKnowledgeSpaceApprovalDialog
                open={!!approvalTarget}
                onOpenChange={(open) => {
                    if (!open) setApprovalTarget(null);
                }}
                space={approvalTarget}
                onSaved={handleDepartmentSpaceSettingsSaved}
                showSensitiveCheckControl={showSensitiveCheckControl}
            />
        </div>
    );
}

// 只负责加载/保存系统提示词、用户提示词、max_chunk_size 的 hook
const useKnowledgeConfig = () => {
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

    // 初始化时从后台读取配置
    useEffect(() => {
        getKnowledgeConfigApi().then((res) => {
            // Interceptor returns response.data.data — null when no config row exists yet.
            const cfg = res != null && typeof res === 'object' ? (res as Record<string, unknown>) : null;
            const systemPromptFromRes = cfg?.system_prompt ?? cfg?.systemPrompt;
            const userPromptFromRes = cfg?.user_prompt ?? cfg?.userPrompt;
            const maxChunkSizeFromRes = cfg?.max_chunk_size ?? cfg?.maxTokens;
            setFormData((prev) => ({
                ...prev,
                systemPrompt: resolveConfigString(systemPromptFromRes, prev.systemPrompt),
                userPrompt: resolveConfigString(userPromptFromRes, prev.userPrompt),
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
