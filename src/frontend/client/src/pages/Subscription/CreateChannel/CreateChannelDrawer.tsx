import { ChevronDown, ChevronRight, PlusSquare, XIcon } from "lucide-react";
import * as RadioGroup from "@radix-ui/react-radio-group";
import { useEffect, useRef, useState, type CSSProperties } from "react";
import { useConfirm, useToastContext } from "~/Providers";
import { NotificationSeverity } from "~/common";
import {
    Sheet,
    SheetContent,
    SheetHeader,
    SheetTitle,
} from "~/components/ui/Sheet";
import { Button } from "~/components/ui/Button";
import { Input } from "~/components/ui/Input";
import { Label } from "~/components/ui/Label";
import { Switch } from "~/components/ui/Switch";
import { Textarea } from "~/components/ui/Textarea";
import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
} from "~/components/ui/AlertDialog";
import { AddSourceDropdown } from "./AddSourceDropdown";
import { CrawlPreviewPanel } from "./CrawlPreviewDialog";
import { CreateChannelSuccessContent } from "./CreateChannelSuccess";
import KnowledgeSyncSection, {
    type KnowledgeSyncDraft,
} from "./KnowledgeSyncSection";
import { SubChannelBlock, type SubChannelData } from "./SubChannelBlock";
import {
    FilterConditionEditor,
    type FilterGroup,
} from "./FilterConditionEditor";
import { validateCreateChannelForm } from "../channelUtils";
import type { Channel, InformationSource } from "~/api/channels";
import { cn, getFullWidthLength, truncateByFullWidth } from "~/utils";
import { useLocalize } from "~/hooks";
import useMediaQuery from "~/hooks/useMediaQuery";
import { useCreateChannelForm } from "../hooks/useCreateChannelForm";

const MAX_CHANNEL_NAME = 10;
const MAX_CHANNEL_DESC = 100;
const MAX_SUB_CHANNELS = 6;

/** 可见方式 / 权限：主标题（私有、需审核、公开）— 与创建知识空间一致 */
const PERMISSION_OPTION_TEXT_CLASS =
    "text-[14px] font-normal leading-[22px] tracking-normal text-[#212121]";
/** 表单说明/辅助文案：14px / 400 / #999999 */
const FORM_HINT_TEXT_CLASS = "text-[14px] font-normal text-[#999999]";
const PERMISSION_OPTION_FONT: CSSProperties = {
    fontFamily: '"PingFang SC", "PingFang TC", -apple-system, BlinkMacSystemFont, "Helvetica Neue", sans-serif',
};

export type { SubChannelData };

export interface CreateChannelFormData {
    sources: InformationSource[];
    channelName: string;
    channelDesc: string;
    visibility: "private" | "review" | "public";
    publishToSquare: "yes" | "no";
    contentFilter: boolean;
    filterGroups: FilterGroup[];
    topFilterRelation: "and" | "or";
    createSubChannel: boolean;
    subChannels: SubChannelData[];
    /** v2.5 Module D — flows through to the `knowledge_sync` field on the
     * Channel create/update payload. */
    knowledgeSync: KnowledgeSyncDraft;
}

interface CreateChannelDrawerProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    onConfirm?: (data: CreateChannelFormData) => Promise<{ channelId: string }>;
    onViewChannel?: (channelId: string) => void;
    onManageMembers?: (channelId: string) => void;
    mode?: "create" | "edit";
    editingChannel?: Channel | null;
}

export function CreateChannelDrawer({
    open,
    onOpenChange,
    onConfirm,
    onViewChannel,
    onManageMembers,
    mode = "create",
    editingChannel = null
}: CreateChannelDrawerProps) {
    const { showToast } = useToastContext();
    const localize = useLocalize();
    const form = useCreateChannelForm();
    const isH5 = useMediaQuery("(max-width: 576px)");
    const isEditMode = mode === "edit" && !!editingChannel;
    const confirm = useConfirm();
    const [isComposingName, setIsComposingName] = useState(false);
    const [isComposingDesc, setIsComposingDesc] = useState(false);
    const initedChannelIdRef = useRef<string | null>(null);
    /** H5：「选择知识空间」下钻层挂载在此容器内，避免与抽屉叠加第二层全屏 Dialog */
    const knowledgePickerHostRef = useRef<HTMLDivElement>(null);
    // v2.5 Module D — owned here so the draft survives across renders of the
    // section and travels with the channel create/update payload on submit.
    const [syncDraft, setSyncDraft] = useState<KnowledgeSyncDraft>({
        main: { enabled: false, spaces: [] },
        subs: [],
    });

    const isCreateFormPristine = () => {
        // 仅用于“创建频道”场景：未做任何修改时，关闭不需要二次确认
        return (
            !isEditMode &&
            form.sources.length === 0 &&
            !form.channelName.trim() &&
            !form.channelDesc.trim() &&
            form.visibility === "review" &&
            form.publishToSquare === "yes" &&
            !form.contentFilter &&
            form.filterGroups.length === 0 &&
            form.topFilterRelation === "and" &&
            !form.createSubChannel &&
            form.subChannels.length === 0
        );
    };
    const [isBodyScrolling, setIsBodyScrolling] = useState(false);
    const bodyScrollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    // Reset the sync draft only on close. Kept in a standalone effect keyed
    // on `open` alone so it does not re-fire when unstable form hook refs
    // change — the main init effect below has a heavier dep list that can
    // flip every render under some localize/query-client setups.
    useEffect(() => {
        if (!open) {
            setSyncDraft({ main: { enabled: false, spaces: [] }, subs: [] });
        }
    }, [open]);

    useEffect(() => {
        if (!open) {
            initedChannelIdRef.current = null;
            return;
        }
        if (open && editingChannel) {
            // Only init once per open+channel to avoid late async updates overriding user's edits.
            if (initedChannelIdRef.current === editingChannel.id) return;
            initedChannelIdRef.current = editingChannel.id;

            // 使用统一表单初始化逻辑（名称 / 简介 / 权限 / 是否发布 / filter_rules）
            form.initFromChannel(editingChannel);

            // v2.5 Module D — hydrate sync draft from channel detail if present.
            const existingSync = (editingChannel as any).knowledge_sync;
            if (existingSync && (existingSync.main || existingSync.subs)) {
                setSyncDraft({
                    main: {
                        enabled: !!existingSync.main?.enabled,
                        spaces: Array.isArray(existingSync.main?.spaces)
                            ? existingSync.main.spaces
                            : [],
                    },
                    subs: Array.isArray(existingSync.subs) ? existingSync.subs : [],
                });
            } else {
                setSyncDraft({ main: { enabled: false, spaces: [] }, subs: [] });
            }

            // 信息源回显：
            const sourceInfos = (editingChannel as any).source_infos as
                | { id: string; source_name: string; source_icon?: string; source_type?: string }[]
                | undefined;

            if (Array.isArray(sourceInfos) && sourceInfos.length > 0) {
                // 详情接口直接返回了完整的信息源信息，优先使用它
                form.setSources(
                    sourceInfos.map((s) => ({
                        id: s.id,
                        name: s.source_name,
                        avatar: s.source_icon,
                        type: s.source_type === "wechat" ? "official_account" : "website",
                    }))
                );
            } else {
                // 退化为根据 source_list ID 列表去 list_sources 反查
                const ids = (editingChannel as any).source_list as string[] | undefined;
                if (ids && ids.length > 0) {
                    form.loadSourcesByIds(ids);
                } else {
                    form.setSources([]);
                }
            }
        }
    }, [
        open,
        editingChannel,
        form.setChannelName,
        form.setChannelDesc,
        form.initFromChannel,
        form.loadSourcesByIds,
        form.setSources
    ]);

    const handleClose = async (nextOpen: boolean) => {
        if (!nextOpen) {
            if (form.showSuccess) {
                form.resetForm();
                onOpenChange(false);
                return;
            }
            if (isCreateFormPristine()) {
                form.resetForm();
                onOpenChange(false);
                return;
            }
            const confirmed = await confirm({
                description: localize("com_subscription.unsaved_tab_confirm_close"),
                cancelText: localize("com_subscription.continue_editing"),
                confirmText: localize("com_subscription.confirm_close")
            });
            if (!confirmed) return;
            form.resetForm();
            onOpenChange(false);
        }
    };

    const handleBodyScroll = () => {
        setIsBodyScrolling(true);
        if (bodyScrollTimerRef.current) {
            clearTimeout(bodyScrollTimerRef.current);
        }
        bodyScrollTimerRef.current = setTimeout(() => {
            setIsBodyScrolling(false);
        }, 500);
    };

    return (
        <>
            <Sheet open={open} onOpenChange={handleClose}>
                <SheetContent
                    side="right"
                    hideClose
                    onScroll={handleBodyScroll}
                    data-scrolling={isBodyScrolling ? "true" : "false"}
                    className={cn(
                        "scroll-on-scroll flex w-full max-w-[900px] flex-col overflow-y-auto overflow-x-hidden bg-white px-20 sm:max-w-[1000px] touch-mobile:px-4",
                        form.crawlDialogOpen && "overflow-hidden"
                    )}
                >
                    <div
                        ref={knowledgePickerHostRef}
                        className="relative flex min-h-0 flex-1 flex-col"
                    >
                    <SheetHeader className="sticky top-0 z-10 mx-6 border-b border-[#E5E6EB] bg-white pb-4 pt-6 touch-mobile:mx-0">
                        <div className="flex items-center justify-between gap-3">
                            <SheetTitle className="-ml-4 text-[20px] font-medium text-[#1D2129] touch-desktop:text-[16px]">
                                {isEditMode ? localize("com_subscription.channel_settings") : localize("com_subscription.create_channel")}
                            </SheetTitle>
                            <button
                                type="button"
                                onClick={() => handleClose(false)}
                                className="ring-offset-background focus:ring-ring data-[state=open]:bg-secondary shrink-0 rounded-xs opacity-70 transition-opacity hover:opacity-100 disabled:pointer-events-none"
                            >
                                <XIcon className="size-4" />
                                <span className="sr-only">Close</span>
                            </button>
                        </div>
                    </SheetHeader>

                    {form.showSuccess && !isEditMode ? (
                        <CreateChannelSuccessContent
                            onViewChannel={() => {
                                if (form.createdChannelId) {
                                    onViewChannel?.(form.createdChannelId);
                                }
                                form.resetForm();
                            }}
                            onManageMembers={() => {
                                if (form.createdChannelId) {
                                    onManageMembers?.(form.createdChannelId);
                                    onViewChannel?.(form.createdChannelId);

                                }
                                form.resetForm();
                                onOpenChange(false);
                            }}
                        />
                    ) : (
                        <div
                            className={cn(
                                "space-y-6 overflow-visible px-6 py-5 touch-mobile:px-0"
                            )}
                        >
                            {/* 添加信息源 */}
                            <div className="space-y-2">
                                <Label className="text-[14px] text-[#1D2129]">
                                    <span className="text-[#F53F3F] mr-1">*</span>
                                    {localize("com_subscription.add_information_source")}
                                </Label>
                                <AddSourceDropdown
                                    sources={form.sources}
                                    onSourcesChange={form.setSources}
                                    expanded={form.showAddSourcePanel}
                                    onExpandChange={form.setShowAddSourcePanel}
                                    resetToken={form.sourceSearchResetToken}
                                    onRequestCrawl={(url) => {
                                        // 打开「确认爬取」前先收起信息源下拉，避免浮层遮挡弹窗
                                        form.setShowAddSourcePanel(false);
                                        form.setCrawlUrl(url);
                                        form.setCrawlDialogOpen(true);
                                    }}
                                />
                            </div>

                            {/* 频道名称 */}
                            <div className="space-y-2">
                                <Label className="text-[14px] text-[#1D2129]">
                                    <span className="text-[#F53F3F] mr-1">*</span>
                                    {localize("com_subscription.channel_name")}
                                </Label>
                                <div className="relative flex gap-2 items-center">
                                    <Input
                                        value={form.channelName}
                                        onChange={(e) => {
                                            const v = e.target.value;
                                            if (isComposingName) {
                                                form.setChannelName(v);
                                                return;
                                            }
                                            if (getFullWidthLength(v) > MAX_CHANNEL_NAME) {
                                                showToast({
                                                    message: localize("com_subscription.maximum_channel_name") || localize("com_subscription.max_10_characters"),
                                                    severity: NotificationSeverity.WARNING
                                                });
                                                form.setChannelName(truncateByFullWidth(v, MAX_CHANNEL_NAME));
                                            } else {
                                                form.setChannelName(v);
                                            }
                                        }}
                                        onCompositionStart={() => setIsComposingName(true)}
                                        onCompositionEnd={(e) => {
                                            setIsComposingName(false);
                                            const v = e.currentTarget.value || "";
                                            if (getFullWidthLength(v) > MAX_CHANNEL_NAME) {
                                                showToast({
                                                    message: localize("com_subscription.maximum_channel_name") || localize("com_subscription.max_10_characters"),
                                                    severity: NotificationSeverity.WARNING
                                                });
                                                form.setChannelName(truncateByFullWidth(v, MAX_CHANNEL_NAME));
                                            } else {
                                                form.setChannelName(v);
                                            }
                                        }}
                                        placeholder={localize("com_subscription.enter_channel_name")}
                                        className="flex-1 h-8 text-[14px] border-[#E5E6EB]"
                                    />
                                    <span className="absolute right-4 flex-shrink-0 text-[12px] text-[#86909C]">
                                        {Math.ceil(getFullWidthLength(form.channelName))}/{MAX_CHANNEL_NAME}
                                    </span>
                                </div>
                            </div>

                            {/* 频道简介 */}
                            <div className="space-y-2">
                                <Label className="text-[14px] text-[#1D2129]">
                                    {localize("com_subscription.channel_description")}
                                </Label>
                                <div className="relative">
                                    <Textarea
                                        value={form.channelDesc}
                                        onChange={(e) => {
                                            const v = e.target.value;
                                            if (isComposingDesc) {
                                                form.setChannelDesc(v);
                                                return;
                                            }
                                            if (getFullWidthLength(v) > MAX_CHANNEL_DESC) {
                                                showToast({
                                                    message: localize("com_subscription.maximum_channel_description") || localize("com_subscription.max_100_characters"),
                                                    severity: NotificationSeverity.WARNING
                                                });
                                                form.setChannelDesc(truncateByFullWidth(v, MAX_CHANNEL_DESC));
                                            } else {
                                                form.setChannelDesc(v);
                                            }
                                        }}
                                        onCompositionStart={() => setIsComposingDesc(true)}
                                        onCompositionEnd={(e) => {
                                            setIsComposingDesc(false);
                                            const v = e.currentTarget.value || "";
                                            if (getFullWidthLength(v) > MAX_CHANNEL_DESC) {
                                                showToast({
                                                    message: localize("com_subscription.maximum_channel_description") || localize("com_subscription.max_100_characters"),
                                                    severity: NotificationSeverity.WARNING
                                                });
                                                form.setChannelDesc(truncateByFullWidth(v, MAX_CHANNEL_DESC));
                                            } else {
                                                form.setChannelDesc(v);
                                            }
                                        }}
                                        placeholder={localize("com_subscription.enter_channel_description")}
                                        className="min-h-[80px] text-[14px] bg-[#fff] rounded-[6px] border-[#E5E6EB] pr-14 shadow-none"
                                    />
                                </div>
                            </div>

                            {/* 可见方式 */}
                            <div className="space-y-3">
                                <Label className="text-[14px] text-[#1D2129]">
                                    <span className="text-[#F53F3F] mr-1">*</span>
                                    {localize("com_subscription.premission_settings")}
                                </Label>
                                <RadioGroup.Root
                                    value={form.visibility}
                                    onValueChange={async (v) => {
                                        // In edit mode, show confirmation when switching to private
                                        if (isEditMode && v === "private" && form.visibility !== "private") {
                                            const confirmed = await confirm({
                                                description: localize("com_subscription.confirm_change_to_private"),
                                                confirmText: localize("com_subscription.change_to_private"),
                                                cancelText: localize("com_subscription.cancel"),
                                            });
                                            if (!confirmed) return;
                                        }
                                        form.setVisibility(v as any);
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
                                            label: localize("com_subscription.publice"),
                                            desc: localize("com_subscription.anyone_can_subscribe")
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

                            {/* 是否发布到广场（仅在非私有时展示） */}
                            {form.visibility !== "private" && (
                                <div className="space-y-3">
                                    <Label className="flex flex-wrap items-baseline gap-x-2 text-[14px] text-[#1D2129]">
                                        <span>
                                            <span className="text-[#F53F3F] mr-1">*</span>
                                            {localize("com_subscription.is_publish_plaza")}
                                        </span>
                                        <span className={FORM_HINT_TEXT_CLASS}>{localize("com_subscription.publish_to_square_description")}</span>
                                    </Label>
                                    <RadioGroup.Root
                                        value={form.publishToSquare}
                                        onValueChange={(v) => form.setPublishToSquare(v as any)}
                                        className="flex gap-6"
                                    >
                                        <label className="flex items-center gap-2 cursor-pointer">
                                            <RadioGroup.Item
                                                value="yes"
                                                className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full border border-[#E5E6EB] bg-white data-[state=checked]:bg-[#165DFF] data-[state=checked]:border-[#165DFF]"
                                            >
                                                <RadioGroup.Indicator className="h-1.5 w-1.5 rounded-full bg-white" />
                                            </RadioGroup.Item>
                                            <span className="text-[14px] text-[#1D2129]">{localize("com_subscription.yes")}</span>
                                        </label>
                                        <label className="flex items-center gap-2 cursor-pointer">
                                            <RadioGroup.Item
                                                value="no"
                                                className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full border border-[#E5E6EB] bg-white data-[state=checked]:bg-[#165DFF] data-[state=checked]:border-[#165DFF]"
                                            >
                                                <RadioGroup.Indicator className="h-1.5 w-1.5 rounded-full bg-white" />
                                            </RadioGroup.Item>
                                            <span className="text-[14px] text-[#1D2129]">{localize("com_subscription.no")}</span>
                                        </label>
                                    </RadioGroup.Root>
                                </div>
                            )}

                            {/* 频道内容筛选 */}
                            <div className="space-y-3">
                                <div className="flex items-start justify-between gap-4">
                                    <div className="min-w-0 pr-2">
                                        <Label className="flex flex-wrap items-baseline gap-x-2 text-[14px] text-[#1D2129]">
                                            <span>{localize("com_subscription.channel_content_filter")}</span>
                                            <span className={FORM_HINT_TEXT_CLASS}>
                                                {localize("com_subscription.only_filter_criteria")}
                                            </span>
                                        </Label>
                                    </div>
                                    <Switch
                                        checked={form.contentFilter}
                                        onCheckedChange={form.handleContentFilterToggle}
                                        className={cn(
                                            "data-[state=checked]:bg-[#165DFF]",
                                            "data-[state=unchecked]:bg-[#E5E6EB]"
                                        )}
                                    />
                                </div>
                                {form.contentFilter && (
                                    <div className="overflow-hidden rounded-[6px] border border-t-[#E5E6EB]">
                                        <div className="flex items-center justify-between gap-2 px-3 py-2 bg-[#F7F8FA]">
                                            <button
                                                type="button"
                                                onClick={() =>
                                                    form.setContentFilterCollapsed(
                                                        (prev) => !prev
                                                    )
                                                }
                                                className="p-1 text-[#86909C] hover:text-[#4E5969] flex-shrink-0"
                                            >
                                                {form.contentFilterCollapsed ? (
                                                    <ChevronRight className="size-4" />
                                                ) : (
                                                    <ChevronDown className="size-4" />
                                                )}
                                            </button>
                                            <span className="flex-1 text-[14px] text-[#1D2129]">
                                                {localize("com_subscription.filter_criteria")}
                                            </span>
                                        </div>
                                        {!form.contentFilterCollapsed && (
                                            <div className="p-3 border-t border-[#E5E6EB]">
                                                <FilterConditionEditor
                                                    groups={form.filterGroups}
                                                    topRelation={form.topFilterRelation}
                                                    onGroupsChange={form.setFilterGroups}
                                                    onTopRelationChange={
                                                        form.setTopFilterRelation
                                                    }
                                                    disableFirstConditionDelete
                                                />
                                            </div>
                                        )}
                                    </div>
                                )}
                            </div>

                            {/* 创建子频道 */}
                            <div className="space-y-3">
                                <div className="flex items-start justify-between gap-4">
                                    <div className="min-w-0 pr-2">
                                        <Label className="flex flex-wrap items-baseline gap-x-2 text-[14px] text-[#1D2129]">
                                            <span>{localize("com_subscription.create_sub_channel")}</span>
                                            <span className={FORM_HINT_TEXT_CLASS}>
                                                {localize("com_subscription.subscribe_same_filters")}
                                            </span>
                                        </Label>
                                    </div>
                                    <Switch
                                        checked={form.createSubChannel}
                                        onCheckedChange={form.handleCreateSubChannelToggle}
                                        className={cn(
                                            "data-[state=checked]:bg-[#165DFF]",
                                            "data-[state=unchecked]:bg-[#E5E6EB]"
                                        )}
                                    />
                                </div>
                                {form.createSubChannel && (
                                    <div className="overflow-hidden rounded-[6px] border border-[#E5E6EB] divide-y divide-[#E5E6EB]">
                                        {form.subChannels.map((sub) => (
                                            <SubChannelBlock
                                                key={sub.id}
                                                data={sub}
                                                openInEditMode={sub.id === form.lastAddedSubChannelId}
                                                onEditModeOpened={() => form.setLastAddedSubChannelId(null)}
                                                onNameChange={(n) =>
                                                    form.handleSubChannelNameChange(sub.id, n)
                                                }
                                                onNameCommitted={(n) => {
                                                    const normalized = n.trim().toLowerCase();
                                                    if (!normalized) return;
                                                    const duplicate = form.subChannels.some(
                                                        (s) =>
                                                            s.id !== sub.id &&
                                                            s.name.trim().toLowerCase() === normalized
                                                    );
                                                    if (!duplicate) return;
                                                    showToast({
                                                        message:
                                                            localize(
                                                                "com_subscription.sub_channel_name_duplicate"
                                                            ) || "子频道名称已存在，请更换",
                                                        severity: NotificationSeverity.WARNING
                                                    });
                                                }}
                                                onRemove={() => form.handleRemoveSubChannel(sub.id)}
                                                onToggleCollapse={() =>
                                                    form.handleSubChannelToggleCollapse(sub.id)
                                                }
                                                onGroupsChange={(groups) =>
                                                    form.handleSubChannelGroupsChange(sub.id, groups)
                                                }
                                                onTopRelationChange={(topRelation) =>
                                                    form.setSubChannels((prev) =>
                                                        prev.map((s) =>
                                                            s.id === sub.id ? { ...s, topRelation } : s
                                                        )
                                                    )
                                                }
                                                onOverLimit={() =>
                                                    showToast({
                                                        message: localize("com_subscription.max_10_characters"),
                                                        severity: NotificationSeverity.WARNING
                                                    })
                                                }
                                                onEmptyName={() =>
                                                    showToast({
                                                        message:
                                                            localize(
                                                                "com_subscription.sub_channel_name_cannot_be_empty"
                                                            ),
                                                        severity: NotificationSeverity.WARNING
                                                    })
                                                }
                                            />
                                        ))}
                                        {form.subChannels.length < MAX_SUB_CHANNELS && (
                                            <button
                                                type="button"
                                                onClick={form.handleAddSubChannel}
                                                className="flex h-12 w-full items-center gap-3 rounded-none bg-[#F8F8F8] px-4 text-left text-[14px] leading-none transition-colors hover:bg-[#F2F3F5]"
                                            >
                                                <PlusSquare className="size-4 shrink-0 text-[#86909C]" />
                                                <span>{localize("com_subscription.add_sub_channel")}</span>
                                            </button>
                                        )}
                                    </div>
                                )}
                            </div>

                            {/* v2.5 Module D — 频道同步至知识空间配置 */}
                            <KnowledgeSyncSection
                                value={syncDraft}
                                onChange={setSyncDraft}
                                mainChannelName={form.channelName.trim()}
                                subChannelNames={
                                    form.createSubChannel
                                        ? form.subChannels
                                            .map((s) => s.name?.trim())
                                            .filter((n): n is string => !!n)
                                        : []
                                }
                                // In create mode the current user is always the creator.
                                // In edit mode, honour the backend's role assignment.
                                isCreator={
                                    !isEditMode ||
                                    String(editingChannel?.role) === "creator"
                                }
                                knowledgePickerHostRef={knowledgePickerHostRef}
                            />
                        </div>
                    )}



                    {/* 底部操作按钮 */}
                    {(!form.showSuccess || isEditMode) && (
                        <div className="sticky bottom-0 z-10 mt-auto mx-6 flex justify-end gap-3 border-t border-[#E5E6EB] bg-white px-0 pb-5 pt-10 touch-mobile:mx-0 touch-mobile:gap-2 touch-mobile:px-0 touch-mobile:pt-4">
                            <Button
                                variant="secondary"
                                onClick={() => handleClose(false)}
                                className="inline-flex h-8 items-center justify-center rounded-[6px] border-none bg-[#F2F3F5] px-4 text-[14px] leading-none !font-normal text-[#4E5969] hover:bg-[#E5E6EB] touch-mobile:flex-1"
                            >
                                {localize("cancel")}
                            </Button>
                            <Button
                                disabled={form.submitting}
                                onClick={async () => {
                                    const data: CreateChannelFormData = {
                                        sources: form.sources,
                                        channelName: form.channelName.trim(),
                                        channelDesc: form.channelDesc.trim(),
                                        visibility: form.visibility,
                                        publishToSquare: form.publishToSquare,
                                        contentFilter: form.contentFilter,
                                        filterGroups: form.filterGroups,
                                        topFilterRelation: form.topFilterRelation,
                                        createSubChannel: form.createSubChannel,
                                        subChannels: form.subChannels,
                                        knowledgeSync: syncDraft,
                                    };

                                    // 创建和编辑统一走同一套校验逻辑：
                                    // 1) 至少 1 个信息源
                                    // 2) 频道名称不能为空
                                    // 3) 主频道 / 子频道筛选条件中的关键词不能为空
                                    const validationError = validateCreateChannelForm(data, localize);
                                    if (validationError) {
                                        showToast({
                                            message: validationError,
                                            severity: NotificationSeverity.WARNING
                                        });
                                        return;
                                    }

                                    if (!onConfirm) return;
                                    try {
                                        form.setSubmitting(true);
                                        const res = await onConfirm(data);
                                        if (!isEditMode) {
                                            form.setCreatedChannelId(res.channelId);
                                            form.setShowSuccess(true);
                                        } else {
                                            showToast({
                                                message: localize("com_subscription.save_success"),
                                                severity: NotificationSeverity.SUCCESS
                                            });
                                            form.resetForm();
                                            onOpenChange(false);
                                        }
                                    } catch {
                                        showToast({
                                            message: localize("channel_create_failed") || localize("com_subscription.create_channel_failed_retry"),
                                            severity: NotificationSeverity.ERROR
                                        });
                                    } finally {
                                        form.setSubmitting(false);
                                    }
                                }}
                                className="inline-flex h-8 items-center justify-center rounded-[6px] border-none bg-[#165DFF] px-4 text-[14px] leading-none !font-normal text-white hover:bg-[#4080FF] disabled:opacity-50 touch-mobile:flex-1"
                            >
                                {isEditMode
                                    ? form.submitting ? localize("com_subscription.saving") : localize("com_subscription.save")
                                    : form.submitting
                                        ? (localize("creating") || localize("com_subscription.creating"))
                                        : (localize("com_subscription.confirm_creation") || localize("com_subscription.confirm_create"))}
                            </Button>
                        </div>
                    )}
                        {form.crawlDialogOpen && (
                            <div
                                className={cn(
                                    isH5 ? "absolute inset-0 z-[70] flex min-h-0 flex-col bg-white" : "fixed inset-0 z-[120] grid place-items-center bg-black/30 p-6",
                                )}
                                onClick={isH5 ? undefined : () => {
                                    form.setShowAddSourcePanel(true);
                                    form.setSourceSearchResetToken((t) => t + 1);
                                    form.setCrawlDialogOpen(false);
                                }}
                            >
                                <div
                                    className={cn(
                                        "min-h-0",
                                        isH5
                                            ? "flex h-full w-full flex-1 flex-col bg-white"
                                            : "flex h-[min(760px,calc(100%-32px))] w-[min(720px,calc(100%-32px))] flex-col overflow-hidden rounded-[8px] border border-[#E5E6EB] bg-white shadow-[0_8px_24px_rgba(0,0,0,0.16)]",
                                    )}
                                    onClick={(event) => event.stopPropagation()}
                                >
                                    <CrawlPreviewPanel
                                        url={form.crawlUrl}
                                        onBack={() => {
                                            form.setShowAddSourcePanel(true);
                                            form.setSourceSearchResetToken((t) => t + 1);
                                            form.setCrawlDialogOpen(false);
                                        }}
                                        onAddSource={(source) => {
                                            form.setSources((prev) => [...prev, source]);
                                            form.setCrawlDialogOpen(false);
                                            form.setShowAddSourcePanel(true);
                                        }}
                                    />
                                </div>
                            </div>
                        )}
                    </div>
                </SheetContent>
            </Sheet>
        </>
    );
}
