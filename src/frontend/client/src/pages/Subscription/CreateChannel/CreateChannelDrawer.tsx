import { ChevronDown, ChevronRight, PlusSquare } from "lucide-react";
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
import { CrawlPreviewDialog } from "./CrawlPreviewDialog";
import { CreateChannelSuccessContent } from "./CreateChannelSuccess";
import { SubChannelBlock, type SubChannelData } from "./SubChannelBlock";
import {
    FilterConditionEditor,
    type FilterGroup,
} from "./FilterConditionEditor";
import { validateCreateChannelForm } from "../channelUtils";
import type { Channel, InformationSource } from "~/api/channels";
import { cn, getFullWidthLength, truncateByFullWidth } from "~/utils";
import { useLocalize } from "~/hooks";
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
    const isEditMode = mode === "edit" && !!editingChannel;
    const confirm = useConfirm();
    const [isComposingName, setIsComposingName] = useState(false);
    const [isComposingDesc, setIsComposingDesc] = useState(false);
    const initedChannelIdRef = useRef<string | null>(null);

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
                    className="w-full max-w-[900px] sm:max-w-[1000px] overflow-y-auto scroll-on-scroll bg-white pl-20 pr-20 flex flex-col"
                    onScroll={handleBodyScroll}
                    data-scrolling={isBodyScrolling ? "true" : "false"}
                >
                    <SheetHeader className="sticky top-0 z-10 ml-6 mr-6 pt-6 pb-4 border-b border-[#E5E6EB] bg-white">
                        <SheetTitle className="text-[16px] -ml-4 font-medium text-[#1D2129]">
                            {isEditMode ? localize("com_subscription.channel_settings") : localize("com_subscription.create_channel")}
                        </SheetTitle>
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
                                "overflow-visible px-6 py-5 space-y-5"
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
                                        className="min-h-[80px] text-[14px] bg-[#fff] rounded-[6px] border-[#E5E6EB] pr-14"
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
                                    <Label className="text-[14px] text-[#1D2129]">
                                        <span className="text-[#F53F3F] mr-1">*</span>
                                        {localize("com_subscription.is_publish_plaza")}
                                        <span className={cn("ml-2", FORM_HINT_TEXT_CLASS)}>{localize("com_subscription.publish_to_square_description")}</span>
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
                                    <div>
                                        <Label className="text-[14px] flex text-[#1D2129]">
                                            {localize("com_subscription.channel_content_filter")}
                                            <p className={cn("ml-2 mt-0.5", FORM_HINT_TEXT_CLASS)}>
                                                {localize("com_subscription.only_filter_criteria")}
                                            </p>
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
                                    <div className="border border-t-[#E5E6EB] overflow-hidden">
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
                                    <div>
                                        <Label className="text-[14px] flex text-[#1D2129]">
                                            {localize("com_subscription.create_sub_channel")}
                                            <p className={cn("ml-2 mt-0.5", FORM_HINT_TEXT_CLASS)}>
                                                {localize("com_subscription.subscribe_same_filters")}
                                            </p>
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
                                    <div className="overflow-hidden border border-[#E5E6EB] divide-y divide-[#E5E6EB]">
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
                        </div>
                    )}

                    {/* 底部操作按钮 */}
                    {(!form.showSuccess || isEditMode) && (
                        <div className="sticky bottom-0 z-10 mt-auto flex justify-end gap-3 px-6 pt-10 pb-5 border-t border-[#E5E6EB] bg-white">
                            <Button
                                variant="secondary"
                                onClick={() => handleClose(false)}
                                className="h-8 rounded-[6px] px-4 inline-flex items-center justify-center leading-none bg-[#F2F3F5] hover:bg-[#E5E6EB] border-none text-[14px] !font-normal text-[#4E5969]"
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
                                        subChannels: form.subChannels
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
                                className="h-8 rounded-[6px] px-4 inline-flex items-center justify-center leading-none bg-[#165DFF] hover:bg-[#4080FF] text-white border-none text-[14px] !font-normal disabled:opacity-50"
                            >
                                {isEditMode
                                    ? form.submitting ? localize("com_subscription.saving") : localize("com_subscription.save")
                                    : form.submitting
                                        ? (localize("creating") || localize("com_subscription.creating"))
                                        : (localize("com_subscription.confirm_creation") || localize("com_subscription.confirm_create"))}
                            </Button>
                        </div>
                    )}
                </SheetContent>
            </Sheet>

            <CrawlPreviewDialog
                open={form.crawlDialogOpen}
                onOpenChange={form.setCrawlDialogOpen}
                url={form.crawlUrl}
                onCancel={() => {
                    // 失败/取消后回到「添加信息源」面板，并清空输入框
                    form.setShowAddSourcePanel(true);
                    form.setSourceSearchResetToken((t) => t + 1);
                }}
                onAddSource={(source) => {
                    form.setSources((prev) => [...prev, source]);
                    form.setCrawlDialogOpen(false);
                    // 添加成功后回到「添加信息源」面板，并展示选中状态
                    form.setShowAddSourcePanel(true);
                }}
            />
        </>
    );
}
