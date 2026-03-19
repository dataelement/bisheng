import { ChevronDown, ChevronRight, PlusSquare } from "lucide-react";
import * as RadioGroup from "@radix-ui/react-radio-group";
import { useEffect, useState } from "react";
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
import { cn } from "~/utils";
import { useLocalize } from "~/hooks";
import { useCreateChannelForm } from "../hooks/useCreateChannelForm";

const MAX_CHANNEL_NAME = 10;
const MAX_CHANNEL_DESC = 100;
const MAX_SUB_CHANNELS = 6;

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

    useEffect(() => {
        if (open && editingChannel) {
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
            const confirmed = await confirm({
                description: localize("com_subscription.unsaved_tab_confirm_close"),
                cancelText: localize("com_subscription.continue_editing"),
                confirmText: localize("com_subscription.confirm_close")
            });
            if (!confirmed) return;
            form.resetForm();
            onOpenChange(false);
        } else {
            form.resetForm();
            onOpenChange(nextOpen);
        }
    };

    return (
        <>
            <Sheet open={open} onOpenChange={handleClose}>
                <SheetContent
                    side="right"
                    className="w-full max-w-[900px] sm:max-w-[1000px] bg-white pl-20 pr-20 flex flex-col"
                >
                    <SheetHeader className="ml-6 mr-6 pt-6 pb-4 border-b border-[#E5E6EB]">
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
                        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
                            {/* 添加信息源 */}
                            <div className="space-y-2">
                                <Label className="text-[14px] text-[#1D2129]">
                                    <span className="text-[#F53F3F]">*</span>
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
                                    <span className="text-[#F53F3F]">*</span>
                                    {localize("com_subscription.channel_name")}
                                </Label>
                                <div className="relative flex gap-2 items-center">
                                    <Input
                                        value={form.channelName}
                                        onChange={(e) => {
                                            const v = e.target.value;
                                            // 中文输入法组合输入阶段不做长度校验，避免提前触发提示
                                            if (isComposingName) {
                                                form.setChannelName(v);
                                                return;
                                            }
                                            if (v.length > MAX_CHANNEL_NAME) {
                                                showToast({
                                                    message: localize("com_subscription.maximum_channel_name") || localize("com_subscription.max_10_characters"),
                                                    severity: NotificationSeverity.WARNING
                                                });
                                                form.setChannelName(v.slice(0, MAX_CHANNEL_NAME));
                                            } else {
                                                form.setChannelName(v);
                                            }
                                        }}
                                        onCompositionStart={() => setIsComposingName(true)}
                                        onCompositionEnd={(e) => {
                                            setIsComposingName(false);
                                            const v = e.currentTarget.value || "";
                                            if (v.length > MAX_CHANNEL_NAME) {
                                                showToast({
                                                    message: localize("com_subscription.maximum_channel_name") || localize("com_subscription.max_10_characters"),
                                                    severity: NotificationSeverity.WARNING
                                                });
                                                form.setChannelName(v.slice(0, MAX_CHANNEL_NAME));
                                            } else {
                                                form.setChannelName(v);
                                            }
                                        }}
                                        placeholder={localize("com_subscription.enter_channel_name")}
                                        className="flex-1 h-10 text-[14px] border-[#E5E6EB]"
                                    />
                                    <span className="absolute right-4 flex-shrink-0 text-[12px] text-[#86909C]">
                                        {form.channelName.length}/{MAX_CHANNEL_NAME}
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
                                            // 中文输入法组合输入阶段不做长度校验，避免提前触发提示
                                            if (isComposingDesc) {
                                                form.setChannelDesc(v);
                                                return;
                                            }
                                            if (v.length > MAX_CHANNEL_DESC) {
                                                showToast({
                                                    message: localize("com_subscription.maximum_channel_description") || localize("com_subscription.max_100_characters"),
                                                    severity: NotificationSeverity.WARNING
                                                });
                                                form.setChannelDesc(v.slice(0, MAX_CHANNEL_DESC));
                                            } else {
                                                form.setChannelDesc(v);
                                            }
                                        }}
                                        onCompositionStart={() => setIsComposingDesc(true)}
                                        onCompositionEnd={(e) => {
                                            setIsComposingDesc(false);
                                            const v = e.currentTarget.value || "";
                                            if (v.length > MAX_CHANNEL_DESC) {
                                                showToast({
                                                    message: localize("com_subscription.maximum_channel_description") || localize("com_subscription.max_100_characters"),
                                                    severity: NotificationSeverity.WARNING
                                                });
                                                form.setChannelDesc(v.slice(0, MAX_CHANNEL_DESC));
                                            } else {
                                                form.setChannelDesc(v);
                                            }
                                        }}
                                        placeholder={localize("com_subscription.enter_channel_description")}
                                        className="min-h-[80px] text-[14px] border-[#E5E6EB] pr-14"
                                    />
                                </div>
                            </div>

                            {/* 可见方式 */}
                            <div className="space-y-3">
                                <Label className="text-[14px] text-[#1D2129]">
                                    <span className="text-[#F53F3F]">*</span>
                                    {localize("com_subscription.premission_settings")}
                                </Label>
                                <RadioGroup.Root
                                    value={form.visibility}
                                    onValueChange={(v) => form.setVisibility(v as any)}
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
                                            <div className="flex">
                                                <span className="text-[14px] text-[#1D2129]">
                                                    {opt.label}
                                                </span>
                                                <p className="text-[12px] text-[#86909C] mt-0.5 ml-2">
                                                    {opt.desc}
                                                </p>
                                            </div>
                                        </label>
                                    ))}
                                </RadioGroup.Root>
                            </div>

                            {/* 是否发布到广场（仅在非私有时展示） */}
                            {form.visibility !== "private" && (
                                <div className="space-y-3">
                                    <Label className="text-[14px] text-[#1D2129]">
                                        <span className="text-[#F53F3F]">*</span>
                                        {localize("com_subscription.is_publish_plaza")}
                                        <span className="ml-2 text-[12px] text-[#86909C]">{localize("com_subscription.publish_to_square_description")}</span>
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
                                            <p className="text-[12px] text-[#86909C] ml-2 mt-0.5">
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
                                            <p className="text-[12px] text-[#86909C] ml-2 mt-0.5">
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
                                    <div className="">
                                        {form.subChannels.map((sub) => (
                                            <SubChannelBlock
                                                key={sub.id}
                                                data={sub}
                                                openInEditMode={sub.id === form.lastAddedSubChannelId}
                                                onEditModeOpened={() => form.setLastAddedSubChannelId(null)}
                                                onNameChange={(n) =>
                                                    form.handleSubChannelNameChange(sub.id, n)
                                                }
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
                                                        message: localize("com_subscription.sub_channel_name_cannot_be_empty"),
                                                        severity: NotificationSeverity.WARNING
                                                    })
                                                }
                                            />
                                        ))}
                                        {form.subChannels.length < MAX_SUB_CHANNELS && (
                                            <button
                                                type="button"
                                                onClick={form.handleAddSubChannel}
                                                className="flex w-full items-center gap-3 px-4 py-2.5 text-[14px] border border-[#E5E6EB] bg-[#F7F8FA] transition-colors"
                                            >
                                                <PlusSquare className="size-4 text-[#86909C]" />
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
                        <div className="flex justify-end gap-3 px-6 py-4 border-t border-[#E5E6EB] bg-white">
                            <Button
                                variant="secondary"
                                onClick={() => handleClose(false)}
                                className="h-9 px-5 bg-[#F2F3F5] hover:bg-[#E5E6EB] border-none text-[14px] text-[#4E5969]"
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
                                className="h-9 px-5 bg-[#165DFF] hover:bg-[#4080FF] text-white border-none text-[14px] disabled:opacity-50"
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
                    // 同时清空搜索输入框状态
                    form.setSourceSearchResetToken((t) => t + 1);
                }}
            />
        </>
    );
}
