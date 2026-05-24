import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ChangeEvent } from "react";
import * as RadioGroup from "@radix-ui/react-radio-group";
import { useQuery } from "@tanstack/react-query";
import { Upload, XIcon } from "lucide-react";
import { NotificationSeverity } from "~/common";
import { useConfirm, useToastContext } from "~/Providers";
import { Button } from "~/components/ui/Button";
import { Input } from "~/components/ui/Input";
import { Label } from "~/components/ui/Label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "~/components/ui/Select";
import {
    Sheet,
    SheetContent,
    SheetHeader,
    SheetTitle
} from "~/components/ui/Sheet";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "~/components/ui/Tabs";
import { Textarea } from "~/components/ui/Textarea";
import { useLocalize } from "~/hooks";
import {
    getCreateSpaceDepartmentsApi,
    getCreateSpaceOptionsApi,
    getCreateSpaceUserGroupsApi,
    getKnowledgeSpaceAutoTagVisibilityApi,
    getKnowledgeSpaceTagLibrariesApi,
    getKnowledgeSpaceTagLibraryDetailApi,
    SpaceLevel,
    VisibilityType,
    type KnowledgeSpace,
    type KnowledgeSpaceTagLibraryListItem,
} from "~/api/knowledge";
import { cn, getFullWidthLength, truncateByFullWidth } from "~/utils";
import { ChannelSuccessIcon } from "~/components/icons/channels";
import type { SelectedSubject } from "~/api/permission";
import { SubjectSearchDepartment, type DepartmentNode } from "~/components/permission/SubjectSearchDepartment";
import { SubjectSearchUserGroup } from "~/components/permission/SubjectSearchUserGroup";

const MAX_SPACE_NAME = 20;
const MAX_SPACE_DESC = 200;
const MAX_AUTO_TAG_CUSTOM_TAGS = 200;
const AUTO_TAG_PREVIEW_LIMIT = 20;

type AutoTagMode = "library" | "custom";

function parseAutoTagText(text: string): string[] {
    const seen = new Set<string>();
    const result: string[] = [];
    for (const line of text.split(/\r?\n/)) {
        const value = line.trim();
        if (!value || seen.has(value)) continue;
        seen.add(value);
        result.push(value);
    }
    return result;
}

/** 权限项文案：PingFang SC / 14px / 22px 行高 / 400 / #212121 */
const PERMISSION_OPTION_TEXT_CLASS =
    "text-[14px] font-normal leading-[22px] tracking-normal text-[#212121]";
/** 权限项说明：14px / 400 / #999999 */
const FORM_HINT_TEXT_CLASS = "text-[14px] font-normal text-[#999999]";
const PERMISSION_OPTION_FONT: CSSProperties = {
    fontFamily: '"PingFang SC", "PingFang TC", -apple-system, BlinkMacSystemFont, "Helvetica Neue", sans-serif',
};

export type JoinPolicy = "private" | "review" | "public";
export type PublishToSquare = "yes" | "no";

export interface CreateKnowledgeSpaceFormData {
    name: string;
    description: string;
    reason?: string;
    joinPolicy: JoinPolicy;
    publishToSquare: PublishToSquare;
    spaceLevel: SpaceLevel;
    departmentId?: number;
    userGroupId?: number;
    autoTagEnabled: boolean;
    autoTagLibraryId: number | null;
    /** Custom tag list when the user picks the "Custom Tags" tab; null when in library mode. */
    autoTagCustomTags: string[] | null;
}

interface CreateKnowledgeSpaceSubmitResult {
    showSuccess?: boolean;
}

interface CreateKnowledgeSpaceDrawerProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    onConfirm?: (data: CreateKnowledgeSpaceFormData) => void | boolean | CreateKnowledgeSpaceSubmitResult | Promise<boolean | void | CreateKnowledgeSpaceSubmitResult>;
    onViewSpace?: () => void;
    onManageMembers?: () => void;
    mode?: "create" | "edit";
    editingSpace?: KnowledgeSpace | null;
    initialSpaceLevel?: SpaceLevel;
    showApprovalReason?: boolean;
}

export function CreateKnowledgeSpaceDrawer({
    open,
    onOpenChange,
    onConfirm,
    onViewSpace,
    onManageMembers,
    mode = "create",
    editingSpace,
    initialSpaceLevel,
    showApprovalReason = false,
}: CreateKnowledgeSpaceDrawerProps) {
    const { showToast } = useToastContext();
    const confirm = useConfirm();
    const localize = useLocalize();
    const [name, setName] = useState("");
    const [description, setDescription] = useState("");
    const [reason, setReason] = useState("");
    const [joinPolicy, setJoinPolicy] = useState<JoinPolicy>("review");
    const [publishToSquare, setPublishToSquare] = useState<PublishToSquare>("yes");
    const [spaceLevel, setSpaceLevel] = useState<SpaceLevel>(SpaceLevel.PERSONAL);
    const [departmentId, setDepartmentId] = useState<number | undefined>();
    const [userGroupId, setUserGroupId] = useState<number | undefined>();
    const [departmentSelection, setDepartmentSelection] = useState<SelectedSubject[]>([]);
    const [userGroupSelection, setUserGroupSelection] = useState<SelectedSubject[]>([]);
    const [autoTagEnabled, setAutoTagEnabled] = useState(false);
    const [autoTagMode, setAutoTagMode] = useState<AutoTagMode>("library");
    const [autoTagLibraryId, setAutoTagLibraryId] = useState<number | null>(null);
    const [autoTagLibraryTags, setAutoTagLibraryTags] = useState<string[]>([]);
    const [autoTagLibraryTagsLoading, setAutoTagLibraryTagsLoading] = useState(false);
    const [autoTagPreviewExpanded, setAutoTagPreviewExpanded] = useState(false);
    const [autoTagCustomTagsText, setAutoTagCustomTagsText] = useState("");
    const [tagLibraries, setTagLibraries] = useState<KnowledgeSpaceTagLibraryListItem[]>([]);
    const [tagLibrariesLoading, setTagLibrariesLoading] = useState(false);
    const [autoTagFeatureVisible, setAutoTagFeatureVisible] = useState(false);
    const customTags = useMemo(
        () => parseAutoTagText(autoTagCustomTagsText),
        [autoTagCustomTagsText],
    );
    const txtInputRef = useRef<HTMLInputElement | null>(null);
    const [showSuccess, setShowSuccess] = useState(false);
    const [submitting, setSubmitting] = useState(false);
    /** Skip max-length enforcement while IME is composing (e.g. Chinese pinyin), so intermediate input is not mistaken as overflow. */
    const nameComposingRef = useRef(false);
    const descComposingRef = useRef(false);

    const needPublishOption = useMemo(
        () => joinPolicy === "review" || joinPolicy === "public",
        [joinPolicy]
    );
    const { data: createOptions } = useQuery({
        queryKey: ["knowledgeSpaces", "createOptions"],
        queryFn: getCreateSpaceOptionsApi,
        enabled: open && mode === "create",
    });

    const approvalCreateMode = mode === "create" && showApprovalReason;

    const loadCreateDepartments = useCallback(async (config?: { signal?: AbortSignal }): Promise<DepartmentNode[]> => {
        const result = await getCreateSpaceDepartmentsApi({
            signal: config?.signal,
            approvalRequest: approvalCreateMode,
        });
        return result.data;
    }, [approvalCreateMode]);

    const loadCreateUserGroups = useCallback(async (config?: { signal?: AbortSignal; keyword?: string }) => {
        const result = await getCreateSpaceUserGroupsApi({
            keyword: config?.keyword,
            pageSize: 50,
            signal: config?.signal,
        });
        return result.data.map((group) => ({
            id: group.id,
            group_name: group.groupName,
        }));
    }, []);

    const levelOptions = useMemo(() => ([
        {
            value: SpaceLevel.PUBLIC,
            label: localize("com_knowledge.public_spaces"),
            enabled: approvalCreateMode || (createOptions?.canCreatePublic ?? false),
        },
        {
            value: SpaceLevel.DEPARTMENT,
            label: localize("com_knowledge.department_spaces"),
            enabled: approvalCreateMode || (createOptions?.canCreateDepartment ?? false),
        },
        {
            value: SpaceLevel.TEAM,
            label: localize("com_knowledge.team_spaces"),
            enabled: approvalCreateMode || (createOptions?.canCreateTeam ?? false),
        },
        {
            value: SpaceLevel.PERSONAL,
            label: localize("com_knowledge.personal_spaces"),
            enabled: createOptions?.canCreatePersonal ?? true,
        },
    ]), [approvalCreateMode, createOptions, localize]);
    const visibleLevelOptions = useMemo(
        () => levelOptions.filter((option) => option.enabled),
        [levelOptions],
    );

    const resetForm = () => {
        setName("");
        setDescription("");
        setReason("");
        setJoinPolicy("review");
        setPublishToSquare("yes");
        setSpaceLevel(SpaceLevel.PERSONAL);
        setDepartmentId(undefined);
        setUserGroupId(undefined);
        setDepartmentSelection([]);
        setUserGroupSelection([]);
        setAutoTagEnabled(false);
        setAutoTagMode("library");
        setAutoTagLibraryId(null);
        setAutoTagLibraryTags([]);
        setAutoTagPreviewExpanded(false);
        setAutoTagCustomTagsText("");
        setShowSuccess(false);
        setSubmitting(false);
    };

    const handleSpaceLevelChange = (value: SpaceLevel) => {
        setSpaceLevel(value);
        if (value !== SpaceLevel.DEPARTMENT) {
            setDepartmentId(undefined);
            setDepartmentSelection([]);
        }
        if (value !== SpaceLevel.TEAM) {
            setUserGroupId(undefined);
            setUserGroupSelection([]);
        }
    };

    // Pre-fill form in edit mode
    useEffect(() => {
        if (!open) {
            resetForm();
            return;
        }
        if (mode === "create") {
            resetForm();
            setSpaceLevel(initialSpaceLevel ?? SpaceLevel.PERSONAL);
            return;
        }
        if (mode === "edit" && editingSpace) {
            setName(editingSpace.name || "");
            setDescription(editingSpace.description || "");
            // Map visibility back to joinPolicy
            setJoinPolicy(
                editingSpace.visibility === VisibilityType.PUBLIC
                    ? "public"
                    : editingSpace.visibility === VisibilityType.PRIVATE
                        ? "private"
                        : "review"
            );
            setPublishToSquare(editingSpace.isReleased ? "yes" : "no");
            setSpaceLevel(editingSpace.spaceLevel || SpaceLevel.PERSONAL);
            setDepartmentId(editingSpace.departmentId);
            setUserGroupId(editingSpace.ownerType === "user_group" ? editingSpace.ownerId : undefined);
            setAutoTagEnabled(Boolean(editingSpace.autoTagEnabled));
            const editingMode: AutoTagMode = editingSpace.autoTagMode === "custom" ? "custom" : "library";
            setAutoTagMode(editingMode);
            if (editingMode === "custom") {
                setAutoTagLibraryId(null);
                setAutoTagCustomTagsText((editingSpace.autoTagCustomTags ?? []).join("\n"));
                setAutoTagLibraryTags([]);
            } else {
                setAutoTagLibraryId(editingSpace.autoTagLibraryId ?? null);
                setAutoTagCustomTagsText("");
            }
            setAutoTagPreviewExpanded(false);
            setShowSuccess(false);
        }
    }, [open, mode, editingSpace, initialSpaceLevel]);

    useEffect(() => {
        if (!open || mode !== "create" || !createOptions) return;
        if (!visibleLevelOptions.some((option) => option.value === spaceLevel)) {
            const next = visibleLevelOptions[0]?.value ?? SpaceLevel.PERSONAL;
            setSpaceLevel(next);
        }
    }, [createOptions, mode, open, spaceLevel, visibleLevelOptions]);

    useEffect(() => {
        if (!open) return;
        // Tenant-level visibility gate: when the admin disables auto-tag
        // generation in the workstation config, hide this section entirely.
        getKnowledgeSpaceAutoTagVisibilityApi()
            .then((res) => setAutoTagFeatureVisible(Boolean(res?.visible)))
            .catch(() => setAutoTagFeatureVisible(false));
    }, [open]);

    useEffect(() => {
        if (!open || !autoTagFeatureVisible) return;
        setTagLibrariesLoading(true);
        getKnowledgeSpaceTagLibrariesApi({ page: 1, page_size: 200 })
            .then((res) => {
                const libraries = res.data || [];
                setTagLibraries(libraries);
                if (!autoTagLibraryId && libraries.length === 1) {
                    setAutoTagLibraryId(libraries[0].id);
                }
            })
            .catch(() => {
                showToast({
                    message: localize("com_knowledge.load_tag_libraries_failed"),
                    severity: NotificationSeverity.WARNING
                });
            })
            .finally(() => setTagLibrariesLoading(false));
    }, [open, autoTagFeatureVisible]);

    // Pull the selected library's full tag list so we can render the preview chips.
    // Only fires in library mode — the custom mode draws its tags from local state.
    useEffect(() => {
        if (!open || !autoTagFeatureVisible) return;
        if (autoTagMode !== "library" || !autoTagLibraryId) {
            setAutoTagLibraryTags([]);
            setAutoTagPreviewExpanded(false);
            return;
        }
        let cancelled = false;
        setAutoTagLibraryTagsLoading(true);
        getKnowledgeSpaceTagLibraryDetailApi(autoTagLibraryId)
            .then((res) => {
                if (cancelled) return;
                setAutoTagLibraryTags(Array.isArray(res.tags) ? res.tags : []);
                setAutoTagPreviewExpanded(false);
            })
            .catch(() => {
                if (cancelled) return;
                setAutoTagLibraryTags([]);
            })
            .finally(() => {
                if (cancelled) return;
                setAutoTagLibraryTagsLoading(false);
            });
        return () => {
            cancelled = true;
        };
    }, [open, autoTagFeatureVisible, autoTagMode, autoTagLibraryId]);

    const handleAutoTagModeChange = (value: string) => {
        const next = value === "custom" ? "custom" : "library";
        setAutoTagMode(next);
        if (next === "custom") {
            setAutoTagLibraryTags([]);
            setAutoTagPreviewExpanded(false);
        }
    };

    const handleUploadTxt = (event: ChangeEvent<HTMLInputElement>) => {
        const file = event.target.files?.[0];
        // Reset the input synchronously so picking the same filename twice in a
        // row still fires onChange.
        event.target.value = "";
        if (!file) return;
        const reader = new FileReader();
        reader.onload = () => {
            const raw = typeof reader.result === "string" ? reader.result : "";
            const parsed = parseAutoTagText(raw);
            if (parsed.length > MAX_AUTO_TAG_CUSTOM_TAGS) {
                showToast({
                    message: localize("com_knowledge.auto_tag_custom_tags_limit"),
                    severity: NotificationSeverity.WARNING,
                });
            }
            setAutoTagCustomTagsText(parsed.slice(0, MAX_AUTO_TAG_CUSTOM_TAGS).join("\n"));
        };
        reader.readAsText(file);
    };

    const handleConfirm = async () => {
        // Guard against double-submit while the previous request is still in-flight.
        if (submitting) return;
        if (!name.trim()) {
            showToast({
                message: localize("com_subscription.knowledge_space_name_empty") || localize("com_knowledge.space_name_empty"),
                severity: NotificationSeverity.WARNING
            });
            return;
        }
        if (spaceLevel === SpaceLevel.DEPARTMENT && !departmentId) {
            showToast({
                message: localize("com_knowledge.department_required"),
                severity: NotificationSeverity.WARNING
            });
            return;
        }
        if (spaceLevel === SpaceLevel.TEAM && !userGroupId) {
            showToast({
                message: localize("com_knowledge.user_group_required"),
                severity: NotificationSeverity.WARNING
            });
            return;
        }
        // When the tenant-level feature is hidden, drop any local state that
        // might have been pre-filled in edit mode so we never submit stale flags.
        const effectiveAutoTagEnabled = autoTagFeatureVisible && autoTagEnabled;
        let effectiveAutoTagLibraryId: number | null = null;
        let effectiveAutoTagCustomTags: string[] | null = null;
        if (effectiveAutoTagEnabled) {
            if (autoTagMode === "library") {
                if (!autoTagLibraryId) {
                    showToast({
                        message: localize("com_knowledge.auto_tag_library_required"),
                        severity: NotificationSeverity.WARNING,
                    });
                    return;
                }
                effectiveAutoTagLibraryId = autoTagLibraryId;
            } else {
                if (customTags.length === 0) {
                    showToast({
                        message: localize("com_knowledge.auto_tag_custom_tags_required"),
                        severity: NotificationSeverity.WARNING,
                    });
                    return;
                }
                if (customTags.length > MAX_AUTO_TAG_CUSTOM_TAGS) {
                    showToast({
                        message: localize("com_knowledge.auto_tag_custom_tags_limit"),
                        severity: NotificationSeverity.WARNING,
                    });
                    return;
                }
                effectiveAutoTagCustomTags = customTags;
            }
        }
        const payload: CreateKnowledgeSpaceFormData = {
            name: name.trim(),
            description: description.trim(),
            reason: mode === "create" && showApprovalReason ? reason.trim() || undefined : undefined,
            joinPolicy,
            publishToSquare: needPublishOption ? publishToSquare : "no",
            spaceLevel,
            departmentId: spaceLevel === SpaceLevel.DEPARTMENT ? departmentId : undefined,
            userGroupId: spaceLevel === SpaceLevel.TEAM ? userGroupId : undefined,
            autoTagEnabled: effectiveAutoTagEnabled,
            autoTagLibraryId: effectiveAutoTagLibraryId,
            autoTagCustomTags: effectiveAutoTagCustomTags,
        };
        try {
            setSubmitting(true);
            const result = await onConfirm?.(payload);
            if (result === false) {
                return;
            }
            const shouldShowSuccess =
                typeof result === "object" && result !== null
                    ? result.showSuccess !== false
                    : true;
            if (mode === "create" && shouldShowSuccess) {
                setShowSuccess(true);
            } else {
                onOpenChange(false);
            }
        } finally {
            setSubmitting(false);
        }
    };

    const handleClose = () => {
        onOpenChange(false);
    };

    return (
        <Sheet open={open} onOpenChange={onOpenChange}>
            <SheetContent
                side="right"
                hideClose
                className={cn(
                    "flex w-full max-w-[900px] flex-col overflow-hidden bg-white px-20 sm:max-w-[1000px] touch-mobile:px-4"
                )}
            >
                <SheetHeader className="sticky top-0 z-10 mx-6 bg-white pb-4 pt-6 touch-mobile:mx-0">
                    <div className="flex items-center justify-between gap-3">
                        <SheetTitle className="-ml-4 text-[20px] font-medium text-[#1D2129] touch-desktop:text-[16px]">
                            {mode === "edit" ? localize("com_subscription.edit_knowledge_space") || localize("com_knowledge.edit_space") : localize("com_subscription.create_konwledge_space")}
                        </SheetTitle>
                        <button
                            type="button"
                            onClick={handleClose}
                            className="ring-offset-background focus:ring-ring data-[state=open]:bg-secondary shrink-0 rounded-xs opacity-70 transition-opacity hover:opacity-100 disabled:pointer-events-none"
                        >
                            <XIcon className="size-4" />
                            <span className="sr-only">Close</span>
                        </button>
                    </div>
                </SheetHeader>

                {showSuccess ? (
                    <div className="flex flex-1 flex-col items-center justify-center py-16">
                        <div className="flex flex-col items-center">
                            <ChannelSuccessIcon className="h-[120px] w-[120px] mb-5" />
                            <div className="mb-8 text-center text-[20px] font-normal text-[#1D2129]">
                                {localize("com_subscription.create_knowledge_space_success")}
                            </div>
                            <div className="flex gap-3">
                                <Button
                                    variant="secondary"
                                    className="inline-flex h-8 min-w-[100px] items-center justify-center rounded-[6px] border border-[#165DFF] bg-white px-4 text-[14px] font-normal leading-none text-[#165DFF] hover:bg-[#E8F3FF]"
                                    onClick={() => {
                                        onViewSpace?.();
                                        onOpenChange(false);
                                    }}
                                >
                                    {localize("com_subscription.goto_knowledge_space")}
                                </Button>
                                <Button
                                    className="inline-flex h-8 min-w-[100px] items-center justify-center rounded-[6px] bg-[#165DFF] px-4 text-[14px] font-normal leading-none text-white hover:bg-[#4080FF]"
                                    onClick={() => {
                                        onManageMembers?.();
                                        onOpenChange(false);
                                    }}
                                >
                                    {localize("com_knowledge.member_management")}
                                </Button>
                            </div>
                        </div>
                    </div>
                ) : (
                    <div className="scroll-on-scroll min-h-0 flex-1 overflow-y-auto overflow-x-hidden">
                        <div className="mx-auto w-full max-w-[800px] space-y-7 overflow-visible px-6 py-5 touch-mobile:max-w-none touch-mobile:px-0">
                            {/* 空间层级 */}
                            <div className="space-y-3">
                                <Label className="text-sm text-[#1D2129] font-medium">
                                    <span className="text-[#F53F3F] mr-1">*</span>
                                    {localize("com_knowledge.space_level")}
                                </Label>
                                {mode === "edit" ? (
                                    <div className="h-8 rounded-[6px] bg-[#F7F8FA] px-3 text-[14px] leading-8 text-[#4E5969]">
                                        {levelOptions.find((option) => option.value === spaceLevel)?.label || spaceLevel}
                                        {editingSpace?.ownerName ? ` - ${editingSpace.ownerName}` : ""}
                                    </div>
                                ) : (
                                    <RadioGroup.Root
                                        value={spaceLevel}
                                        onValueChange={(value) => handleSpaceLevelChange(value as SpaceLevel)}
                                        className="grid grid-cols-2 gap-3 touch-mobile:grid-cols-1"
                                    >
                                        {visibleLevelOptions.map((option) => (
                                            <label
                                                key={option.value}
                                                className="flex cursor-pointer items-center gap-2 rounded-[6px] border border-[#E5E6EB] px-3 py-2 text-[14px] text-[#212121]"
                                            >
                                                <RadioGroup.Item
                                                    value={option.value}
                                                    className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full border border-[#E5E6EB] bg-white data-[state=checked]:border-[#165DFF] data-[state=checked]:bg-[#165DFF]"
                                                >
                                                    <RadioGroup.Indicator className="h-1.5 w-1.5 rounded-full bg-white" />
                                                </RadioGroup.Item>
                                                <span>{option.label}</span>
                                            </label>
                                        ))}
                                    </RadioGroup.Root>
                                )}
                                {mode === "create" && spaceLevel === SpaceLevel.DEPARTMENT && (
                                    <div className="space-y-2">
                                        <Label className="text-sm text-[#1D2129] font-medium">
                                            <span className="text-[#F53F3F] mr-1">*</span>
                                            {localize("com_knowledge.select_department")}
                                        </Label>
                                        <div className="h-[260px]">
                                            <SubjectSearchDepartment
                                                value={departmentSelection}
                                                onChange={(next) => {
                                                    setDepartmentSelection(next);
                                                    setDepartmentId(next[0]?.id);
                                                }}
                                                includeChildren={false}
                                                onIncludeChildrenChange={() => undefined}
                                                loadDepartments={loadCreateDepartments}
                                                selectionMode="single"
                                            />
                                        </div>
                                    </div>
                                )}
                                {mode === "create" && spaceLevel === SpaceLevel.TEAM && (
                                    <div className="space-y-2">
                                        <Label className="text-sm text-[#1D2129] font-medium">
                                            <span className="text-[#F53F3F] mr-1">*</span>
                                            {localize("com_knowledge.select_user_group")}
                                        </Label>
                                        <div className="h-[260px]">
                                            <SubjectSearchUserGroup
                                                value={userGroupSelection}
                                                onChange={(next) => {
                                                    setUserGroupSelection(next);
                                                    setUserGroupId(next[0]?.id);
                                                }}
                                                loadUserGroups={loadCreateUserGroups}
                                                selectionMode="single"
                                            />
                                        </div>
                                    </div>
                                )}
                            </div>

                            {/* 知识空间名称 */}
                            <div className="space-y-2">
                                <Label className="text-sm text-[#1D2129] font-medium">
                                    <span className="text-[#F53F3F] mr-1">*</span>
                                    {localize("com_subscription.knowledge_space_name")}
                                </Label>
                                <div className="relative flex items-center gap-2">
                                    <Input
                                        value={name}
                                        onCompositionStart={() => {
                                            nameComposingRef.current = true;
                                        }}
                                        onCompositionEnd={(e) => {
                                            nameComposingRef.current = false;
                                            const v = e.currentTarget.value;
                                            if (getFullWidthLength(v) > MAX_SPACE_NAME) {
                                                showToast({
                                                    message: localize("com_subscription.max_knowledge_space_name") || localize("com_knowledge.max_20_chars"),
                                                    severity: NotificationSeverity.WARNING
                                                });
                                                setName(truncateByFullWidth(v, MAX_SPACE_NAME));
                                            }
                                        }}
                                        onChange={(e) => {
                                            const v = e.target.value;
                                            if (nameComposingRef.current) {
                                                setName(v);
                                                return;
                                            }
                                            if (getFullWidthLength(v) > MAX_SPACE_NAME) {
                                                showToast({
                                                    message: localize("com_subscription.max_knowledge_space_name") || localize("com_knowledge.max_20_chars"),
                                                    severity: NotificationSeverity.WARNING
                                                });
                                                setName(truncateByFullWidth(v, MAX_SPACE_NAME));
                                            } else {
                                                setName(v);
                                            }
                                        }}
                                        placeholder={localize("com_subscription.enter_knowledge_space_name")}
                                        className="h-8 border-[#E5E6EB] text-[14px] pr-16 bg-[#fff]"
                                    />
                                    <span className="absolute right-4 text-[12px] text-[#86909C]">
                                        {Math.ceil(getFullWidthLength(name))}/{MAX_SPACE_NAME}
                                    </span>
                                </div>
                            </div>

                            {/* 简介 */}
                            <div className="space-y-2">
                                <Label className="text-sm text-[#1D2129] font-medium">
                                    {localize("com_subscription.description")}
                                </Label>
                                <div>
                                    <Textarea
                                        value={description}
                                        onCompositionStart={() => {
                                            descComposingRef.current = true;
                                        }}
                                        onCompositionEnd={(e) => {
                                            descComposingRef.current = false;
                                            const v = e.currentTarget.value;
                                            if (getFullWidthLength(v) > MAX_SPACE_DESC) {
                                                showToast({
                                                    message: localize("com_subscription.max_knowledge_space_desc") || localize("com_knowledge.max_200_chars"),
                                                    severity: NotificationSeverity.WARNING
                                                });
                                                setDescription(truncateByFullWidth(v, MAX_SPACE_DESC));
                                            }
                                        }}
                                        onChange={(e) => {
                                            const v = e.target.value;
                                            if (descComposingRef.current) {
                                                setDescription(v);
                                                return;
                                            }
                                            if (getFullWidthLength(v) > MAX_SPACE_DESC) {
                                                showToast({
                                                    message: localize("com_subscription.max_knowledge_space_desc") || localize("com_knowledge.max_200_chars"),
                                                    severity: NotificationSeverity.WARNING
                                                });
                                                setDescription(truncateByFullWidth(v, MAX_SPACE_DESC));
                                            } else {
                                                setDescription(v);
                                            }
                                        }}
                                        placeholder={localize("com_subscription.enter_knowledge_space_description")}
                                        className="min-h-[104px] rounded-[6px] border-[#E5E6EB] bg-[#fff] text-[14px]"
                                    />
                                </div>
                            </div>

                            {mode === "create" && showApprovalReason && (
                                <div className="space-y-2">
                                    <Label className="text-sm text-[#1D2129] font-medium">
                                        申请意见
                                    </Label>
                                    <Textarea
                                        value={reason}
                                        onChange={(e) => setReason(e.target.value)}
                                        placeholder="请输入申请意见"
                                        className="min-h-[88px] rounded-[6px] border-[#E5E6EB] bg-[#fff] text-[14px]"
                                    />
                                </div>
                            )}

                            {/* 权限设置 */}
                            <div className="space-y-3">
                                <Label className="text-sm text-[#1D2129] font-medium">
                                    <span className="text-[#F53F3F]">*</span>
                                    {localize("com_subscription.premission_settings")}
                                </Label>
                                <RadioGroup.Root
                                    value={joinPolicy}
                                    onValueChange={async (v) => {
                                        if (mode === "edit" && v === "private" && joinPolicy !== "private") {
                                            const confirmed = await confirm({
                                                description: localize("com_subscription.confirm_knowledge_change_to_private"),
                                                confirmText: localize("com_subscription.change_to_private"),
                                                cancelText: localize("com_subscription.cancel"),
                                            });
                                            if (!confirmed) return;
                                        }
                                        setJoinPolicy(v as JoinPolicy);
                                    }}
                                    className="flex flex-col gap-3"
                                >
                                    {[
                                        {
                                            value: "private",
                                            label: localize("com_subscription.private"),
                                            desc: localize("com_subscription.cannot_subscribe")
                                        },
                                        {
                                            value: "review",
                                            label: localize("com_subscription.approval_required"),
                                            desc: localize("com_subscription.require_approval")
                                        },
                                        {
                                            value: "public",
                                            label: localize("com_subscription.public"),
                                            desc: localize("com_subscription.anyone_can_subscribe") || localize("com_knowledge.direct_subscribe_desc")
                                        }
                                    ].map((opt) => (
                                        <label
                                            key={opt.value}
                                            className="flex items-start gap-2 cursor-pointer"
                                        >
                                            <RadioGroup.Item
                                                value={opt.value}
                                                className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border border-[#E5E6EB] bg-white data-[state=checked]:bg-[#165DFF] data-[state=checked]:border-[#165DFF]"
                                            >
                                                <RadioGroup.Indicator className="h-1.5 w-1.5 rounded-full bg-white" />
                                            </RadioGroup.Item>
                                            <div className="flex flex-wrap items-baseline gap-x-2">
                                                <span
                                                    className={PERMISSION_OPTION_TEXT_CLASS}
                                                    style={PERMISSION_OPTION_FONT}
                                                >
                                                    {opt.label}
                                                </span>
                                                <span className={FORM_HINT_TEXT_CLASS}>
                                                    {opt.desc}
                                                </span>
                                            </div>
                                        </label>
                                    ))}
                                </RadioGroup.Root>
                            </div>

                            {/* 是否发布到知识广场 */}
                            {needPublishOption && (
                                <div className="space-y-3">
                                    <Label className="text-[14px] text-[#1D2129]">
                                        <span className="text-[#F53F3F]">*</span>
                                        {localize("com_knowledge.publish_to_square")}<span className={cn("ml-2", FORM_HINT_TEXT_CLASS)}>
                                            {localize("com_knowledge.publish_desc")}</span>
                                    </Label>
                                    <RadioGroup.Root
                                        value={publishToSquare}
                                        onValueChange={(v) => setPublishToSquare(v as PublishToSquare)}
                                        className="flex gap-6"
                                    >
                                        <label className="flex items-center gap-2 cursor-pointer">
                                            <RadioGroup.Item
                                                value="yes"
                                                className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full border border-[#E5E6EB] bg-white data-[state=checked]:bg-[#165DFF] data-[state=checked]:border-[#165DFF]"
                                            >
                                                <RadioGroup.Indicator className="h-1.5 w-1.5 rounded-full bg-white" />
                                            </RadioGroup.Item>
                                            <span className="text-[14px] text-[#1D2129]">{localize("com_knowledge.yes")}</span>
                                        </label>
                                        <label className="flex items-center gap-2 cursor-pointer">
                                            <RadioGroup.Item
                                                value="no"
                                                className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full border border-[#E5E6EB] bg-white data-[state=checked]:bg-[#165DFF] data-[state=checked]:border-[#165DFF]"
                                            >
                                                <RadioGroup.Indicator className="h-1.5 w-1.5 rounded-full bg-white" />
                                            </RadioGroup.Item>
                                            <span className="text-[14px] text-[#1D2129]">{localize("com_knowledge.no")}</span>
                                        </label>
                                    </RadioGroup.Root>
                                </div>
                            )}

                            {autoTagFeatureVisible && (
                                <div className="space-y-3">
                                    <Label className="text-[14px] text-[#1D2129]">
                                        <span className="text-[#F53F3F]">*</span>
                                        {localize("com_knowledge.auto_tag_generation")}
                                        <span className={cn("ml-2", FORM_HINT_TEXT_CLASS)}>
                                            {localize("com_knowledge.auto_tag_generation_desc")}
                                        </span>
                                    </Label>
                                    <RadioGroup.Root
                                        value={autoTagEnabled ? "yes" : "no"}
                                        onValueChange={(v) => {
                                            const checked = v === "yes";
                                            setAutoTagEnabled(checked);
                                            if (!checked) return;
                                            if (!autoTagLibraryId && tagLibraries.length === 1) {
                                                setAutoTagLibraryId(tagLibraries[0].id);
                                            }
                                        }}
                                        className="flex gap-6"
                                    >
                                        <label className="flex items-center gap-2 cursor-pointer">
                                            <RadioGroup.Item
                                                value="yes"
                                                className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full border border-[#E5E6EB] bg-white data-[state=checked]:bg-[#165DFF] data-[state=checked]:border-[#165DFF]"
                                            >
                                                <RadioGroup.Indicator className="h-1.5 w-1.5 rounded-full bg-white" />
                                            </RadioGroup.Item>
                                            <span className="text-[14px] text-[#1D2129]">{localize("com_knowledge.yes")}</span>
                                        </label>
                                        <label className="flex items-center gap-2 cursor-pointer">
                                            <RadioGroup.Item
                                                value="no"
                                                className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full border border-[#E5E6EB] bg-white data-[state=checked]:bg-[#165DFF] data-[state=checked]:border-[#165DFF]"
                                            >
                                                <RadioGroup.Indicator className="h-1.5 w-1.5 rounded-full bg-white" />
                                            </RadioGroup.Item>
                                            <span className="text-[14px] text-[#1D2129]">{localize("com_knowledge.no")}</span>
                                        </label>
                                    </RadioGroup.Root>

                                    {autoTagEnabled && (
                                        <Tabs
                                            value={autoTagMode}
                                            onValueChange={handleAutoTagModeChange}
                                            className="space-y-3"
                                        >
                                            <TabsList className="h-8 gap-1 rounded-[6px] border border-[#E5E6EB] bg-white p-1">
                                                <TabsTrigger
                                                    value="library"
                                                    className="min-w-0 px-3 py-1 text-[13px] data-[state=active]:bg-[#E8F3FF] data-[state=active]:text-[#165DFF]"
                                                >
                                                    {localize("com_knowledge.auto_tag_mode_library")}
                                                </TabsTrigger>
                                                <TabsTrigger
                                                    value="custom"
                                                    className="min-w-0 px-3 py-1 text-[13px] data-[state=active]:bg-[#E8F3FF] data-[state=active]:text-[#165DFF]"
                                                >
                                                    {localize("com_knowledge.auto_tag_mode_custom")}
                                                </TabsTrigger>
                                            </TabsList>

                                            <TabsContent value="library" className="space-y-2">
                                                <Label className="text-[14px] font-medium text-[#1D2129]">
                                                    <span className="mr-1 text-[#F53F3F]">*</span>
                                                    {localize("com_knowledge.auto_tag_library")}
                                                </Label>
                                                <Select
                                                    value={autoTagLibraryId ? String(autoTagLibraryId) : undefined}
                                                    onValueChange={(value) => setAutoTagLibraryId(Number(value))}
                                                    disabled={tagLibrariesLoading || tagLibraries.length === 0}
                                                >
                                                    <SelectTrigger className="h-8 border-[#E5E6EB] bg-white text-[14px]">
                                                        <SelectValue
                                                            placeholder={
                                                                tagLibrariesLoading
                                                                    ? localize("com_knowledge.loading")
                                                                    : localize("com_knowledge.select_auto_tag_library")
                                                            }
                                                        />
                                                    </SelectTrigger>
                                                    <SelectContent className="z-[150] bg-white">
                                                        {tagLibraries.map((library) => (
                                                            <SelectItem key={library.id} value={String(library.id)}>
                                                                {library.name}
                                                            </SelectItem>
                                                        ))}
                                                    </SelectContent>
                                                </Select>
                                                {tagLibraries.length === 0 && !tagLibrariesLoading && (
                                                    <p className="text-[12px] text-[#F53F3F]">
                                                        {localize("com_knowledge.no_auto_tag_library")}
                                                    </p>
                                                )}
                                                {autoTagLibraryId && (
                                                    <div className="space-y-1.5 pt-1">
                                                        <div className="text-[12px] text-[#86909C]">
                                                            {localize("com_knowledge.auto_tag_library_preview")}
                                                        </div>
                                                        {autoTagLibraryTagsLoading ? (
                                                            <div className="text-[12px] text-[#86909C]">
                                                                {localize("com_knowledge.loading")}
                                                            </div>
                                                        ) : autoTagLibraryTags.length === 0 ? (
                                                            <div className="text-[12px] text-[#86909C]">
                                                                {localize("com_knowledge.auto_tag_library_preview_empty")}
                                                            </div>
                                                        ) : (
                                                            <div className="flex flex-wrap items-center">
                                                                {(autoTagPreviewExpanded
                                                                    ? autoTagLibraryTags
                                                                    : autoTagLibraryTags.slice(0, AUTO_TAG_PREVIEW_LIMIT)
                                                                ).map((tag, idx) => (
                                                                    <span
                                                                        key={`${tag}-${idx}`}
                                                                        className="mb-1.5 mr-1.5 inline-flex items-center rounded-full bg-[#E8F3FF] px-2 py-0.5 text-[12px] text-[#165DFF]"
                                                                    >
                                                                        {tag}
                                                                    </span>
                                                                ))}
                                                                {autoTagLibraryTags.length > AUTO_TAG_PREVIEW_LIMIT && (
                                                                    <button
                                                                        type="button"
                                                                        className="mb-1.5 text-[12px] text-[#165DFF] hover:underline"
                                                                        onClick={() => setAutoTagPreviewExpanded((prev) => !prev)}
                                                                    >
                                                                        {autoTagPreviewExpanded
                                                                            ? localize("com_knowledge.collapse")
                                                                            : `${localize("com_knowledge.expand_more")} (+${autoTagLibraryTags.length - AUTO_TAG_PREVIEW_LIMIT})`}
                                                                    </button>
                                                                )}
                                                            </div>
                                                        )}
                                                    </div>
                                                )}
                                            </TabsContent>

                                            <TabsContent value="custom" className="space-y-2">
                                                <div className="flex items-center justify-between">
                                                    <Label className="text-[14px] font-medium text-[#1D2129]">
                                                        <span className="mr-1 text-[#F53F3F]">*</span>
                                                        {localize("com_knowledge.auto_tag_mode_custom")}
                                                    </Label>
                                                    <span className="text-[12px] text-[#86909C]">
                                                        {customTags.length}/{MAX_AUTO_TAG_CUSTOM_TAGS}
                                                    </span>
                                                </div>
                                                <div className="relative">
                                                    <Textarea
                                                        value={autoTagCustomTagsText}
                                                        onChange={(e) => setAutoTagCustomTagsText(e.target.value)}
                                                        placeholder={localize("com_knowledge.auto_tag_custom_tags_placeholder")}
                                                        className="min-h-[120px] resize-none rounded-[6px] border-[#E5E6EB] bg-white pr-24 text-[14px]"
                                                    />
                                                    <button
                                                        type="button"
                                                        onClick={() => txtInputRef.current?.click()}
                                                        className="absolute right-2 top-2 inline-flex cursor-pointer items-center gap-1 text-[12px] text-[#165DFF] hover:underline"
                                                    >
                                                        <Upload className="h-3 w-3" />
                                                        {localize("com_knowledge.upload_txt")}
                                                    </button>
                                                    <input
                                                        ref={txtInputRef}
                                                        type="file"
                                                        accept=".txt"
                                                        className="hidden"
                                                        onChange={handleUploadTxt}
                                                    />
                                                </div>
                                            </TabsContent>
                                        </Tabs>
                                    )}
                                </div>
                            )}
                        </div>
                    </div>
                )}

                {!showSuccess && (
                    <div className="sticky bottom-0 z-10 mt-auto mx-6 flex justify-end gap-3 bg-white px-0 pb-5 pt-10 touch-mobile:mx-0 touch-mobile:gap-2 touch-mobile:px-0 touch-mobile:pt-4">
                        <div className="mx-auto flex w-full max-w-[800px] justify-end gap-3 touch-mobile:max-w-none">
                            <Button
                                variant="secondary"
                                className="inline-flex h-8 items-center justify-center rounded-[6px] border-none bg-[#F2F3F5] px-4 text-[14px] leading-none !font-normal text-[#4E5969] hover:bg-[#E5E6EB] touch-mobile:flex-1"
                                onClick={() => onOpenChange(false)}
                            >
                                {localize("com_knowledge.cancel")}</Button>
                            <Button
                                disabled={submitting}
                                className="inline-flex h-8 items-center justify-center rounded-[6px] border-none bg-[#165DFF] px-4 text-[14px] leading-none !font-normal text-white hover:bg-[#4080FF] disabled:opacity-50 disabled:cursor-not-allowed touch-mobile:flex-1"
                                onClick={handleConfirm}
                            >
                                {submitting
                                    ? (mode === "edit" ? localize("com_subscription.saving") : localize("com_subscription.creating"))
                                    : (mode === "edit" ? localize("com_knowledge.save") : localize("com_knowledge.confirm_create"))}
                            </Button>
                        </div>
                    </div>
                )}
            </SheetContent>
        </Sheet>
    );
}
