import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import * as RadioGroup from "@radix-ui/react-radio-group";
import { useQuery } from "@tanstack/react-query";
import { XIcon } from "lucide-react";
import { NotificationSeverity } from "~/common";
import { useConfirm, useToastContext } from "~/Providers";
import { Button } from "~/components/ui/Button";
import { Input } from "~/components/ui/Input";
import { Label } from "~/components/ui/Label";
import MultiSelect from "~/components/ui/MultiSelect";
import {
    Sheet,
    SheetContent,
    SheetHeader,
    SheetTitle,
} from "~/components/ui/Sheet";
import { Textarea } from "~/components/ui/Textarea";
import { useLocalize } from "~/hooks";
import {
    getCreateSpaceOptionsApi,
    getCreateSpaceDepartmentsApi,
    getKnowledgeSpaceTagLibrariesApi,
    getKnowledgeSpaceTagLibrariesByKnowledgeApi,
    getKnowledgeSpaceTagLibraryDetailApi,
    getSpaceInfoApi,
    SpaceLevel,
    VisibilityType,
    type KnowledgeSpace,
    type KnowledgeSpaceTagLibraryListItem,
} from "~/api/knowledge";
import type { SelectedSubject } from "~/api/permission";
import { cn, getFullWidthLength, truncateByFullWidth } from "~/utils";
import { ChannelSuccessIcon } from "~/components/icons/channels";
import { SubjectSearchDepartment, type DepartmentNode } from "~/components/permission/SubjectSearchDepartment";

const MAX_SPACE_NAME = 20;
const MAX_SPACE_DESC = 200;
const AUTO_TAG_PREVIEW_LIMIT = 10;

function normalizeTagLibraryId(value: unknown): number | null {
    const id = Number(value);
    return Number.isFinite(id) && id > 0 ? id : null;
}

function resolveEditingSpaceLibraryIds(space?: KnowledgeSpace | null): number[] {
    if (!space) return [];
    if (space.autoTagLibraryIds?.length) {
        return space.autoTagLibraryIds
            .map(normalizeTagLibraryId)
            .filter((id): id is number => id !== null);
    }
    const legacyId = normalizeTagLibraryId(space.autoTagLibraryId);
    return legacyId ? [legacyId] : [];
}

function mergeLibraryIdSources(...groups: Array<number[] | undefined | null>): number[] {
    const merged: number[] = [];
    const seen = new Set<number>();
    for (const group of groups) {
        for (const rawId of group ?? []) {
            const id = normalizeTagLibraryId(rawId);
            if (!id || seen.has(id)) continue;
            seen.add(id);
            merged.push(id);
        }
    }
    return merged;
}

function mergeTagLibraryListItems(
    ...groups: KnowledgeSpaceTagLibraryListItem[][]
): KnowledgeSpaceTagLibraryListItem[] {
    const merged = new Map<number, KnowledgeSpaceTagLibraryListItem>();
    for (const group of groups) {
        for (const library of group) {
            const id = normalizeTagLibraryId(library?.id);
            if (id) {
                merged.set(id, { ...library, id });
            }
        }
    }
    return Array.from(merged.values());
}

async function hydrateMissingTagLibraries(
    libraryIds: number[],
    current: KnowledgeSpaceTagLibraryListItem[],
): Promise<KnowledgeSpaceTagLibraryListItem[]> {
    const merged = new Map<number, KnowledgeSpaceTagLibraryListItem>(
        mergeTagLibraryListItems(current).map((library) => [library.id, library]),
    );
    const missingIds = libraryIds.filter((id) => !merged.has(id));
    if (!missingIds.length) {
        return Array.from(merged.values());
    }
    const details = await Promise.all(
        missingIds.map((id) => getKnowledgeSpaceTagLibraryDetailApi(id).catch(() => null)),
    );
    for (const detail of details) {
        if (!detail?.id) continue;
        merged.set(detail.id, {
            id: detail.id,
            name: detail.name,
            description: detail.description ?? null,
            tag_count: detail.tag_count ?? 0,
            is_builtin: Boolean(detail.is_builtin),
        });
    }
    return Array.from(merged.values());
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
    autoTagLibraryIds: number[];
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
    showSuccessManageMembers?: boolean | ((spaceLevel: SpaceLevel) => boolean);
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
    showSuccessManageMembers = true,
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
    const [publishToSquare, setPublishToSquare] = useState<PublishToSquare>("no");
    const [spaceLevel, setSpaceLevel] = useState<SpaceLevel>(SpaceLevel.PERSONAL);
    const [departmentSelection, setDepartmentSelection] = useState<SelectedSubject[]>([]);
    const [autoTagEnabled, setAutoTagEnabled] = useState(false);
    const [autoTagLibraryIds, setAutoTagLibraryIds] = useState<number[]>([]);
    const [autoTagLibraryTags, setAutoTagLibraryTags] = useState<string[]>([]);
    const [autoTagLibraryTagsLoading, setAutoTagLibraryTagsLoading] = useState(false);
    const [tagLibraries, setTagLibraries] = useState<KnowledgeSpaceTagLibraryListItem[]>([]);
    const [tagLibrariesLoading, setTagLibrariesLoading] = useState(false);
    const [showSuccess, setShowSuccess] = useState(false);
    const [submitting, setSubmitting] = useState(false);
    /** Skip max-length enforcement while IME is composing (e.g. Chinese pinyin), so intermediate input is not mistaken as overflow. */
    const nameComposingRef = useRef(false);
    const descComposingRef = useRef(false);

    const needPublishOption = useMemo(
        () => joinPolicy === "review" || joinPolicy === "public",
        [joinPolicy]
    );
    const editingLibraryIds = useMemo(
        () => resolveEditingSpaceLibraryIds(editingSpace),
        [editingSpace],
    );
    const tagLibrarySelectOptions = useMemo(() => {
        const optionMap = new Map<string, { label: string; value: string }>();
        for (const library of tagLibraries) {
            const id = normalizeTagLibraryId(library.id);
            if (!id) continue;
            optionMap.set(String(id), {
                label: library.name || `#${id}`,
                value: String(id),
            });
        }
        for (const id of autoTagLibraryIds) {
            const value = String(id);
            if (!optionMap.has(value)) {
                optionMap.set(value, { label: `#${id}`, value });
            }
        }
        return Array.from(optionMap.values());
    }, [tagLibraries, autoTagLibraryIds]);
    const originalEditJoinPolicy = useMemo<JoinPolicy>(() => {
        if (!editingSpace?.visibility) return joinPolicy;
        if (editingSpace.visibility === VisibilityType.PUBLIC) return "public";
        if (editingSpace.visibility === VisibilityType.PRIVATE) return "private";
        if (editingSpace.visibility === VisibilityType.APPROVAL) return "review";
        return joinPolicy;
    }, [editingSpace?.visibility, joinPolicy]);
    const originalEditPublishToSquare = useMemo<PublishToSquare>(() => {
        if (!editingSpace || typeof editingSpace.isReleased !== "boolean") return publishToSquare;
        return editingSpace.isReleased ? "yes" : "no";
    }, [editingSpace, publishToSquare]);
    const { data: createOptions } = useQuery({
        queryKey: ["knowledgeSpaces", "createOptions"],
        queryFn: getCreateSpaceOptionsApi,
        enabled: open && mode === "create",
    });

    const levelOptions = useMemo(() => ([
        {
            value: SpaceLevel.PUBLIC,
            label: localize("com_knowledge.public_spaces"),
            enabled: createOptions?.canCreatePublic ?? false,
        },
        {
            value: SpaceLevel.DEPARTMENT,
            label: localize("com_knowledge.department_spaces"),
            enabled: createOptions?.canCreateDepartment ?? false,
        },
        {
            value: SpaceLevel.TEAM,
            label: localize("com_knowledge.team_spaces"),
            enabled: createOptions?.canCreateTeam ?? false,
        },
        {
            value: SpaceLevel.PERSONAL,
            label: localize("com_knowledge.personal_spaces"),
            enabled: createOptions?.canCreatePersonal ?? true,
        },
    ]), [createOptions, localize]);
    const enabledLevelOptions = useMemo(
        () => levelOptions.filter((option) => option.enabled),
        [levelOptions],
    );
    const visibleLevelOptions = useMemo(
        () => {
            if (mode !== "create") return enabledLevelOptions;
            return enabledLevelOptions.filter((option) => option.value === spaceLevel);
        },
        [enabledLevelOptions, mode, spaceLevel],
    );
    const selectedLevelCreateEnabled = useMemo(() => {
        if (mode !== "create") return true;
        return Boolean(levelOptions.find((option) => option.value === spaceLevel)?.enabled);
    }, [levelOptions, mode, spaceLevel]);
    const shouldShowVisibilityControls = false;
    const shouldShowPublishOption = shouldShowVisibilityControls && needPublishOption;
    const shouldShowDepartmentSelector = mode === "create"
        && spaceLevel === SpaceLevel.DEPARTMENT
        && selectedLevelCreateEnabled;
    const shouldShowApprovalReason = mode === "create"
        && showApprovalReason
        && spaceLevel === SpaceLevel.TEAM;
    const confirmDisabled = submitting || (mode === "create" && !selectedLevelCreateEnabled);
    const selectedDepartmentId = departmentSelection[0]?.id;

    const resetForm = () => {
        setName("");
        setDescription("");
        setReason("");
        setJoinPolicy("review");
        setPublishToSquare("no");
        setSpaceLevel(SpaceLevel.PERSONAL);
        setDepartmentSelection([]);
        setAutoTagEnabled(false);
        setAutoTagLibraryIds([]);
        setAutoTagLibraryTags([]);
        setShowSuccess(false);
        setSubmitting(false);
    };

    const handleSpaceLevelChange = (value: SpaceLevel) => {
        setSpaceLevel(value);
        if (value !== SpaceLevel.DEPARTMENT) {
            setDepartmentSelection([]);
        }
    };

    const loadCreateDepartments = useCallback(async (config?: { signal?: AbortSignal }): Promise<DepartmentNode[]> => {
        const res = await getCreateSpaceDepartmentsApi({
            page: 1,
            pageSize: 100,
            approvalRequest: showApprovalReason,
            signal: config?.signal,
        });
        return res.data;
    }, [showApprovalReason]);

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
            setAutoTagEnabled(Boolean(editingSpace.autoTagEnabled));
            setAutoTagLibraryTags([]);
            setShowSuccess(false);
        }
    }, [open, mode, editingSpace, initialSpaceLevel]);

    useEffect(() => {
        if (!open || mode !== "create" || !createOptions) return;
        if (!enabledLevelOptions.some((option) => option.value === spaceLevel)) {
            const next = enabledLevelOptions[0]?.value ?? SpaceLevel.PERSONAL;
            setSpaceLevel(next);
        }
    }, [createOptions, enabledLevelOptions, mode, open, spaceLevel]);

    useEffect(() => {
        if (!open) {
            setTagLibrariesLoading(false);
            return;
        }
        let cancelled = false;
        setTagLibrariesLoading(true);
        const spaceId = editingSpace?.id;

        const loadTagLibraries = async () => {
            try {
                const [globalResult, boundResult, infoResult] = await Promise.allSettled([
                    getKnowledgeSpaceTagLibrariesApi({ page: 1, page_size: 200 }),
                    mode === "edit" && spaceId
                        ? getKnowledgeSpaceTagLibrariesByKnowledgeApi(spaceId)
                        : Promise.resolve([] as KnowledgeSpaceTagLibraryListItem[]),
                    mode === "edit" && spaceId
                        ? getSpaceInfoApi(spaceId)
                        : Promise.resolve(null),
                ]);
                if (cancelled) return;

                const globalLibraries = globalResult.status === "fulfilled"
                    ? (globalResult.value.data || [])
                    : [];
                const boundLibraries = boundResult.status === "fulfilled"
                    ? boundResult.value
                    : [];
                const infoSpace = infoResult.status === "fulfilled" ? infoResult.value : null;

                const boundIdsFromApi = boundLibraries
                    .map((library) => normalizeTagLibraryId(library.id))
                    .filter((id): id is number => id !== null);
                const selectedIds = mode === "edit"
                    ? mergeLibraryIdSources(
                        boundIdsFromApi,
                        resolveEditingSpaceLibraryIds(infoSpace),
                        resolveEditingSpaceLibraryIds(editingSpace),
                        editingLibraryIds,
                    )
                    : [];

                let mergedLibraries = mergeTagLibraryListItems(globalLibraries, boundLibraries);
                if (mode === "edit" && selectedIds.length > 0) {
                    mergedLibraries = await hydrateMissingTagLibraries(selectedIds, mergedLibraries);
                    if (!cancelled) {
                        setAutoTagLibraryIds(selectedIds);
                    }
                }
                if (!cancelled) {
                    setTagLibraries(mergedLibraries);
                }
            } catch {
                if (!cancelled) {
                    showToast({
                        message: localize("com_knowledge.load_tag_libraries_failed"),
                        severity: NotificationSeverity.WARNING,
                    });
                    const fallbackIds = mode === "edit"
                        ? mergeLibraryIdSources(editingLibraryIds, resolveEditingSpaceLibraryIds(editingSpace))
                        : [];
                    if (mode === "edit" && fallbackIds.length > 0) {
                        const hydrated = await hydrateMissingTagLibraries(fallbackIds, []);
                        if (!cancelled) {
                            setTagLibraries(hydrated);
                            setAutoTagLibraryIds(fallbackIds);
                        }
                    } else if (!cancelled) {
                        setTagLibraries([]);
                    }
                }
            } finally {
                if (!cancelled) {
                    setTagLibrariesLoading(false);
                }
            }
        };

        void loadTagLibraries();

        return () => {
            cancelled = true;
        };
    }, [open, mode, editingSpace?.id, editingLibraryIds.join(",")]);

    useEffect(() => {
        if (!open) return;
        if (autoTagLibraryIds.length === 0) {
            setAutoTagLibraryTags([]);
            return;
        }
        let cancelled = false;
        setAutoTagLibraryTagsLoading(true);
        Promise.all(autoTagLibraryIds.map((libraryId) => getKnowledgeSpaceTagLibraryDetailApi(libraryId)))
            .then((results) => {
                if (cancelled) return;
                const seen = new Set<string>();
                const merged: string[] = [];
                for (const result of results) {
                    for (const tag of result.tags || []) {
                        if (seen.has(tag)) continue;
                        seen.add(tag);
                        merged.push(tag);
                    }
                }
                setAutoTagLibraryTags(merged);
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
    }, [open, autoTagLibraryIds]);

    const handleConfirm = async () => {
        // Guard against double-submit while the previous request is still in-flight.
        if (submitting) return;
        if (!name.trim()) {
            showToast({
                message: localize("com_knowledge.space_name_empty"),
                severity: NotificationSeverity.WARNING
            });
            return;
        }
        if (mode === "create" && !selectedLevelCreateEnabled) {
            return;
        }
        if (shouldShowDepartmentSelector && !selectedDepartmentId) {
            showToast({
                message: "请选择部门",
                severity: NotificationSeverity.WARNING
            });
            return;
        }
        const effectiveAutoTagEnabled = autoTagEnabled;
        if (effectiveAutoTagEnabled && autoTagLibraryIds.length === 0) {
            showToast({
                message: localize("com_knowledge.auto_tag_library_required"),
                severity: NotificationSeverity.WARNING,
            });
            return;
        }
        const effectiveJoinPolicy: JoinPolicy = mode === "edit" ? originalEditJoinPolicy : "review";
        const payload: CreateKnowledgeSpaceFormData = {
            name: name.trim(),
            description: description.trim(),
            ...(shouldShowApprovalReason && reason.trim() ? { reason: reason.trim() } : {}),
            joinPolicy: effectiveJoinPolicy,
            publishToSquare: mode === "edit" ? originalEditPublishToSquare : "no",
            spaceLevel,
            departmentId: shouldShowDepartmentSelector ? selectedDepartmentId : undefined,
            userGroupId: undefined,
            autoTagEnabled: effectiveAutoTagEnabled,
            autoTagLibraryIds,
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

    const shouldShowSuccessManageMembers = typeof showSuccessManageMembers === "function"
        ? showSuccessManageMembers(spaceLevel)
        : showSuccessManageMembers;

    return (
        <Sheet open={open} onOpenChange={onOpenChange}>
            <SheetContent
                side="right"
                hideClose
                className={cn(
                    "flex w-full max-w-[800px] flex-col gap-0 overflow-hidden bg-white px-4 sm:max-w-[800px]"
                )}
            >
                <SheetHeader className="sticky top-0 z-10 bg-white px-0">
                    <div className="flex items-center justify-between gap-3">
                        <SheetTitle className="text-[20px] font-medium text-[#1D2129] touch-desktop:text-[16px]">
                            {mode === "edit" ? localize("com_knowledge.edit_space") : localize("com_knowledge.create_knowledge_space")}
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
                                {localize("com_knowledge.space_create_success")}
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
                                    前往知识库
                                </Button>
                                {shouldShowSuccessManageMembers ? (
                                    <Button
                                        className="inline-flex h-8 min-w-[100px] items-center justify-center rounded-[6px] bg-[#165DFF] px-4 text-[14px] font-normal leading-none text-white hover:bg-[#4080FF]"
                                        onClick={() => {
                                            onManageMembers?.();
                                            onOpenChange(false);
                                        }}
                                    >
                                        {localize("com_knowledge.member_management")}
                                    </Button>
                                ) : null}
                            </div>
                        </div>
                    </div>
                ) : (
                    <div className="scroll-on-scroll min-h-0 flex-1 overflow-y-auto overflow-x-hidden">
                        <div className="w-full space-y-7 overflow-visible pb-5">
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
                                {shouldShowDepartmentSelector && (
                                    <div className="space-y-2">
                                        <Label className="text-sm text-[#1D2129] font-medium">
                                            <span className="text-[#F53F3F] mr-1">*</span>
                                            选择部门
                                        </Label>
                                        <SubjectSearchDepartment
                                            value={departmentSelection}
                                            onChange={setDepartmentSelection}
                                            includeChildren
                                            onIncludeChildrenChange={() => undefined}
                                            selectionMode="single"
                                            loadDepartments={loadCreateDepartments}
                                        />
                                    </div>
                                )}
                            </div>

                            {/* 知识空间名称 */}
                            <div className="space-y-2">
                                <Label className="text-sm text-[#1D2129] font-medium">
                                    <span className="text-[#F53F3F] mr-1">*</span>
                                    知识库名称
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
                                        placeholder="请输入知识库名称"
                                        className="h-8 border-[#E5E6EB] text-[14px] pr-16 bg-[#fff]"
                                    />
                                    <span className="absolute right-4 text-[12px] text-[#86909C]">
                                        {Math.ceil(getFullWidthLength(name))}/{MAX_SPACE_NAME}
                                    </span>
                                </div>
                            </div>

                            <div className="space-y-2">
                                <Label className="text-[14px] font-medium text-[#1D2129]">
                                    {localize("com_knowledge.auto_tag_library")}
                                </Label>
                                <MultiSelect
                                    key={`${editingSpace?.id ?? "create"}-${autoTagLibraryIds.join(",")}-${tagLibrarySelectOptions.length}`}
                                    multiple
                                    className="w-full"
                                    value={autoTagLibraryIds.map(String)}
                                    options={tagLibrarySelectOptions}
                                    placeholder={
                                        tagLibrariesLoading
                                            ? localize("com_knowledge.loading")
                                            : localize("com_knowledge.select_auto_tag_library")
                                    }
                                    disabled={tagLibrariesLoading}
                                    onChange={(values) => setAutoTagLibraryIds(values.map(Number))}
                                />
                                {tagLibraries.length === 0 && !tagLibrariesLoading && (
                                    <p className="text-[12px] text-[#F53F3F]">
                                        {localize("com_knowledge.no_auto_tag_library")}
                                    </p>
                                )}
                                {autoTagLibraryIds.length > 0 && (
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
                                                {autoTagLibraryTags.slice(0, AUTO_TAG_PREVIEW_LIMIT).map((tag, idx) => (
                                                    <span
                                                        key={`${tag}-${idx}`}
                                                        className="mb-1.5 mr-1.5 inline-flex items-center rounded-full bg-[#E8F3FF] px-2 py-0.5 text-[12px] text-[#165DFF]"
                                                    >
                                                        {tag}
                                                    </span>
                                                ))}
                                            </div>
                                        )}
                                    </div>
                                )}
                            </div>

                            {shouldShowApprovalReason && (
                                <div className="space-y-2">
                                    <Label className="text-sm text-[#1D2129] font-medium">
                                        申请理由
                                    </Label>
                                    <Textarea
                                        value={reason}
                                        onChange={(e) => setReason(e.target.value)}
                                        placeholder="请输入申请理由"
                                        className="min-h-[88px] rounded-[6px] border-[#E5E6EB] bg-[#fff] text-[14px]"
                                    />
                                </div>
                            )}

                            {shouldShowVisibilityControls && (
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
                            )}

                            {/* 是否发布到知识广场 */}
                            {shouldShowPublishOption && (
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
                                    onValueChange={(v) => setAutoTagEnabled(v === "yes")}
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
                                        placeholder="请输入知识库简介"
                                        className="min-h-[104px] rounded-[6px] border-[#E5E6EB] bg-[#fff] text-[14px]"
                                    />
                                </div>
                            </div>
                        </div>
                    </div>
                )}

                {!showSuccess && (
                    <div className="sticky bottom-0 z-10 mt-auto flex justify-end gap-3 bg-white pb-5 pt-10 touch-mobile:gap-2 touch-mobile:pt-4">
                        <div className="flex w-full justify-end gap-3">
                            <Button
                                variant="secondary"
                                className="inline-flex h-8 items-center justify-center rounded-[6px] border-none bg-[#F2F3F5] px-4 text-[14px] leading-none !font-normal text-[#4E5969] hover:bg-[#E5E6EB] touch-mobile:flex-1"
                                onClick={() => onOpenChange(false)}
                            >
                                {localize("com_knowledge.cancel")}</Button>
                            <Button
                                disabled={confirmDisabled}
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
