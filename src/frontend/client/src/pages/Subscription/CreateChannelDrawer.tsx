import { ChevronDown, ChevronRight, Pencil, Plus, PlusSquare, Trash2 } from "lucide-react";
import * as RadioGroup from "@radix-ui/react-radio-group";
import { useState, useCallback, useRef, useEffect } from "react";
import { useToastContext } from "~/Providers";
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
import {
    FilterConditionEditor,
    validateFilterGroups,
    type FilterConditionItem,
    type FilterGroup,
    type FilterRelation,
} from "./FilterConditionEditor";
import type { InformationSource } from "~/mock/sources";
import { cn, generateUUID } from "~/utils";
import { useLocalize } from "~/hooks";

const MAX_SOURCES = 50;
const MAX_CHANNEL_NAME = 10;
const MAX_CHANNEL_DESC = 100;
const MAX_SUB_CHANNELS = 6;

type VisibilityType = "private" | "approval" | "public";
type PublishToSquare = "yes" | "no";

export interface SubChannelData {
    id: string;
    name: string;
    collapsed: boolean;
    groups: FilterGroup[];
    topRelation: FilterRelation;
}

export interface CreateChannelFormData {
    sources: InformationSource[];
    channelName: string;
    channelDesc: string;
    visibility: VisibilityType;
    publishToSquare: PublishToSquare;
    contentFilter: boolean;
    filterGroups: FilterGroup[];
    topFilterRelation: FilterRelation;
    createSubChannel: boolean;
    subChannels: SubChannelData[];
}

interface CreateChannelDrawerProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    onConfirm?: (data: CreateChannelFormData) => Promise<{ channelId: string }>;
    createdChannelCount?: number;
    /** 创建成功后点击「查看频道」 */
    onViewChannel?: () => void;
    /** 创建成功后点击「成员管理」 */
    onManageMembers?: (channelId: string) => void;
}

const MAX_USER_CHANNELS = 10;

function nanoid() {
    return generateUUID(8);
}

export function CreateChannelDrawer({
    open,
    onOpenChange,
    onConfirm,
    createdChannelCount = 0,
    onViewChannel,
    onManageMembers
}: CreateChannelDrawerProps) {
    const { showToast } = useToastContext();
    const localize = useLocalize();
    const [sources, setSources] = useState<InformationSource[]>([]);
    const [channelName, setChannelName] = useState("");
    const [channelDesc, setChannelDesc] = useState("");
    const [visibility, setVisibility] = useState<VisibilityType>("public");
    const [publishToSquare, setPublishToSquare] = useState<PublishToSquare>("no");
    const [contentFilter, setContentFilter] = useState(false);
    const [contentFilterCollapsed, setContentFilterCollapsed] = useState(false);
    const [filterGroups, setFilterGroups] = useState<FilterGroup[]>([]);
    const [topFilterRelation, setTopFilterRelation] = useState<FilterRelation>("and");
    const [createSubChannel, setCreateSubChannel] = useState(false);
    const [subChannels, setSubChannels] = useState<SubChannelData[]>([]);
    const [showAddSourcePanel, setShowAddSourcePanel] = useState(false);
    const [showCancelConfirm, setShowCancelConfirm] = useState(false);
    const [crawlDialogOpen, setCrawlDialogOpen] = useState(false);
    const [crawlUrl, setCrawlUrl] = useState("");
    const [showSuccess, setShowSuccess] = useState(false);
    const [submitting, setSubmitting] = useState(false);
    const [createdChannelId, setCreatedChannelId] = useState<string | null>(null);
    /** 刚添加的子频道 id，用于自动进入编辑并全选「子频道名称」 */
    const [lastAddedSubChannelId, setLastAddedSubChannelId] = useState<string | null>(null);

    const resetForm = useCallback(() => {
        setSources([]);
        setChannelName("");
        setChannelDesc("");
        setVisibility("public");
        setPublishToSquare("no");
        setContentFilter(false);
        setFilterGroups([]);
        setTopFilterRelation("and");
        setCreateSubChannel(false);
        setSubChannels([]);
        setLastAddedSubChannelId(null);
        setShowAddSourcePanel(false);
        setShowCancelConfirm(false);
        setCrawlDialogOpen(false);
        setCrawlUrl("");
        setShowSuccess(false);
        setSubmitting(false);
        setCreatedChannelId(null);
    }, []);

    const handleClose = (nextOpen: boolean) => {
        if (!nextOpen) {
            if (showSuccess) {
                resetForm();
                onOpenChange(false);
                return;
            }
            setShowCancelConfirm(true);
        } else {
            resetForm();
            onOpenChange(nextOpen);
        }
    };

    const confirmClose = () => {
        resetForm();
        setShowCancelConfirm(false);
        onOpenChange(false);
    };

    const handleAddSubChannel = () => {
        if (subChannels.length >= MAX_SUB_CHANNELS) return;
        const id = nanoid();
        setSubChannels([
            ...subChannels,
            {
                id,
                name: "子频道名称",
                collapsed: false,
                groups: [{ id: nanoid(), relation: "and", conditions: [{ id: nanoid(), include: true, keywords: "" }] }],
                topRelation: "and"
            }
        ]);
        setLastAddedSubChannelId(id);
    };

    const handleRemoveSubChannel = (id: string) => {
        const next = subChannels.filter((s) => s.id !== id);
        setSubChannels(next);
        if (next.length === 0) setCreateSubChannel(false);
    };

    const handleSubChannelNameChange = (id: string, name: string) => {
        const trimmed = name.slice(0, MAX_CHANNEL_NAME);
        setSubChannels((prev) =>
            prev.map((s) => (s.id === id ? { ...s, name: trimmed } : s))
        );
    };

    const handleSubChannelToggleCollapse = (id: string) => {
        setSubChannels((prev) =>
            prev.map((s) => (s.id === id ? { ...s, collapsed: !s.collapsed } : s))
        );
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
                            {localize("create_channel")}
                        </SheetTitle>
                    </SheetHeader>

                    {showSuccess ? (
                        <CreateChannelSuccessContent
                            onViewChannel={() => {
                                onViewChannel?.();
                                resetForm();
                                onOpenChange(false);
                            }}
                            onManageMembers={() => {
                                if (createdChannelId) {
                                    onManageMembers?.(createdChannelId);
                                }
                                resetForm();
                                onOpenChange(false);
                            }}
                        />
                    ) : (
                        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
                            {/* 添加信息源 - 有层级的下拉式，添加完/添加时两种状态，原先添加区展开后变为搜索框 */}
                            <div className="space-y-2">
                                <Label className="text-[14px] text-[#1D2129]">
                                    <span className="text-[#F53F3F]">*</span>
                                    {localize("add_information_source")}
                                </Label>
                                <AddSourceDropdown
                                    sources={sources}
                                    onSourcesChange={setSources}
                                    expanded={showAddSourcePanel}
                                    onExpandChange={setShowAddSourcePanel}
                                    onRequestCrawl={(url) => {
                                        setCrawlUrl(url);
                                        setCrawlDialogOpen(true);
                                    }}
                                />
                            </div>

                            {/* 频道名称 */}
                            <div className="space-y-2">
                                <Label className="text-[14px] text-[#1D2129]">
                                    <span className="text-[#F53F3F]">*</span>
                                    {localize("channel_name")}
                                </Label>
                                <div className="relative flex gap-2 items-center">
                                    <Input
                                        value={channelName}
                                        onChange={(e) => {
                                            const v = e.target.value;
                                            if (v.length > MAX_CHANNEL_NAME) {
                                                showToast({
                                                    message: localize("maximum_channel_name") || "最多输入 10 个字符",
                                                    severity: NotificationSeverity.WARNING
                                                });
                                                setChannelName(v.slice(0, MAX_CHANNEL_NAME));
                                            } else {
                                                setChannelName(v);
                                            }
                                        }}
                                        placeholder={localize("enter_channel_name") || "请输入频道名称"}
                                        className="flex-1 h-10 text-[14px] border-[#E5E6EB]"
                                    />
                                    <span className="absolute right-4 flex-shrink-0 text-[12px] text-[#86909C]">
                                        {channelName.length}/{MAX_CHANNEL_NAME}
                                    </span>
                                </div>
                            </div>

                            {/* 频道简介 */}
                            <div className="space-y-2">
                                <Label className="text-[14px] text-[#1D2129]">
                                    {localize("channel_description")}
                                </Label>
                                <div className="relative">
                                    <Textarea
                                        value={channelDesc}
                                        onChange={(e) => {
                                            const v = e.target.value;
                                            if (v.length > MAX_CHANNEL_DESC) {
                                                showToast({
                                                    message: localize("maximum_channel_description") || "最多输入 100 个字符",
                                                    severity: NotificationSeverity.WARNING
                                                });
                                                setChannelDesc(v.slice(0, MAX_CHANNEL_DESC));
                                            } else {
                                                setChannelDesc(v);
                                            }
                                        }}
                                        placeholder={localize("enter_channel_description") || "请输入频道简介"}
                                        className="min-h-[80px] text-[14px] border-[#E5E6EB] pr-14"
                                    />
                                </div>
                            </div>

                            {/* 可见方式 */}
                            <div className="space-y-3">
                                <Label className="text-[14px] text-[#1D2129]">
                                    <span className="text-[#F53F3F]">*</span>
                                    {localize("premission_settings")}
                                </Label>
                                <RadioGroup.Root
                                    value={visibility}
                                    onValueChange={(v) => setVisibility(v as VisibilityType)}
                                    className="flex flex-col gap-3"
                                >
                                    {[
                                        {
                                            value: "private",
                                            label: localize("private"),
                                            desc: localize("cannot_subscribe")
                                        },
                                        {
                                            value: "approval",
                                            label: localize("approval_required"),
                                            desc: localize("require_approval")
                                        },
                                        {
                                            value: "public",
                                            label: localize("publice"),
                                            desc: localize("anyone_can_subscribe") || "任何人可直接订阅,无需审核"
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

                            {/* 是否发布到广场 */}
                            <div className="space-y-3">
                                <Label className="text-[14px] text-[#1D2129]">
                                    <span className="text-[#F53F3F]">*</span>
                                    {localize("is_publish_plaza")}
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
                                        <span className="text-[14px] text-[#1D2129]">是</span>
                                    </label>
                                    <label className="flex items-center gap-2 cursor-pointer">
                                        <RadioGroup.Item
                                            value="no"
                                            className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full border border-[#E5E6EB] bg-white data-[state=checked]:bg-[#165DFF] data-[state=checked]:border-[#165DFF]"
                                        >
                                            <RadioGroup.Indicator className="h-1.5 w-1.5 rounded-full bg-white" />
                                        </RadioGroup.Item>
                                        <span className="text-[14px] text-[#1D2129]">否</span>
                                    </label>
                                </RadioGroup.Root>
                            </div>

                            {/* 频道内容筛选 */}
                            <div className="space-y-3">
                                <div className="flex items-start justify-between gap-4">
                                    <div>
                                        <Label className="text-[14px] flex text-[#1D2129]">
                                            {localize("channel_content_filter")}
                                            <p className="text-[12px] text-[#86909C] ml-2 mt-0.5">
                                                {localize("only_filter_criteria")}
                                            </p>
                                        </Label>
                                    </div>
                                    <Switch
                                        checked={contentFilter}
                                        onCheckedChange={(v) => {
                                            setContentFilter(v);
                                            if (v && filterGroups.length === 0) {
                                                setFilterGroups([
                                                    {
                                                        id: nanoid(),
                                                        relation: "and",
                                                        conditions: [
                                                            {
                                                                id: nanoid(),
                                                                include: true,
                                                                keywords: ""
                                                            }
                                                        ]
                                                    }
                                                ]);
                                            }
                                        }}
                                        className={cn(
                                            "data-[state=checked]:bg-[#165DFF]",
                                            "data-[state=unchecked]:bg-[#E5E6EB]"
                                        )}
                                    />
                                </div>
                                {contentFilter && (
                                    <div className="border border-t-[#E5E6EB] overflow-hidden">
                                        <div className="flex items-center justify-between gap-2 px-3 py-2 bg-[#F7F8FA]">
                                            <button
                                                type="button"
                                                onClick={() =>
                                                    setContentFilterCollapsed(
                                                        (prev) => !prev
                                                    )
                                                }
                                                className="p-1 text-[#86909C] hover:text-[#4E5969] flex-shrink-0"
                                            >
                                                {contentFilterCollapsed ? (
                                                    <ChevronRight className="size-4" />
                                                ) : (
                                                    <ChevronDown className="size-4" />
                                                )}
                                            </button>
                                            <span className="flex-1 text-[14px] text-[#1D2129]">
                                                {localize("filter_criteria")}
                                            </span>
                                        </div>
                                        {!contentFilterCollapsed && (
                                            <div className="p-3 border-t border-[#E5E6EB]">
                                                <FilterConditionEditor
                                                    groups={filterGroups}
                                                    topRelation={topFilterRelation}
                                                    onGroupsChange={setFilterGroups}
                                                    onTopRelationChange={
                                                        setTopFilterRelation
                                                    }
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
                                            {localize("create_sub_channel")}
                                            <p className="text-[12px] text-[#86909C] ml-2 mt-0.5">
                                                {localize("subscribe_same_filters")}
                                            </p>
                                        </Label>
                                    </div>
                                    <Switch
                                        checked={createSubChannel}
                                        onCheckedChange={(v) => {
                                            setCreateSubChannel(v);
                                            if (v && subChannels.length === 0)
                                                handleAddSubChannel();
                                        }}
                                        className={cn(
                                            "data-[state=checked]:bg-[#165DFF]",
                                            "data-[state=unchecked]:bg-[#E5E6EB]"
                                        )}
                                    />
                                </div>
                                {createSubChannel && (
                                    <div className="">
                                        {subChannels.map((sub) => (
                                            <SubChannelBlock
                                                key={sub.id}
                                                data={sub}
                                                openInEditMode={sub.id === lastAddedSubChannelId}
                                                onEditModeOpened={() => setLastAddedSubChannelId(null)}
                                                onNameChange={(n) =>
                                                    handleSubChannelNameChange(sub.id, n)
                                                }
                                                onRemove={() => handleRemoveSubChannel(sub.id)}
                                                onToggleCollapse={() =>
                                                    handleSubChannelToggleCollapse(sub.id)
                                                }
                                                onGroupsChange={(groups) =>
                                                    setSubChannels((prev) =>
                                                        prev.map((s) =>
                                                            s.id === sub.id ? { ...s, groups } : s
                                                        )
                                                    )
                                                }
                                                onTopRelationChange={(topRelation) =>
                                                    setSubChannels((prev) =>
                                                        prev.map((s) =>
                                                            s.id === sub.id ? { ...s, topRelation } : s
                                                        )
                                                    )
                                                }
                                                onOverLimit={() =>
                                                    showToast({
                                                        message: "最多输入 10 个字符",
                                                        severity: NotificationSeverity.WARNING
                                                    })
                                                }
                                                onEmptyName={() =>
                                                    showToast({
                                                        message: "子频道名称不能为空",
                                                        severity: NotificationSeverity.WARNING
                                                    })
                                                }
                                            />
                                        ))}
                                        {subChannels.length < MAX_SUB_CHANNELS && (
                                            <button
                                                type="button"
                                                onClick={handleAddSubChannel}
                                                className="flex w-full items-center gap-3 px-4 py-2.5 text-[14px] border border-[#E5E6EB] bg-[#F7F8FA] transition-colors"
                                            >
                                                <PlusSquare className="size-4 text-[#86909C]" />
                                                <span>{localize("add_sub_channel")}</span>
                                            </button>
                                        )}
                                    </div>
                                )}
                            </div>
                        </div>
                    )}

                    {/* 底部操作按钮：仅在表单时显示 */}
                    {!showSuccess && (
                        <div className="flex justify-end gap-3 px-6 py-4 border-t border-[#E5E6EB] bg-white">
                            <Button
                                variant="secondary"
                                onClick={() => handleClose(false)}
                                className="h-9 px-5 bg-[#F2F3F5] hover:bg-[#E5E6EB] border-none text-[14px] text-[#4E5969]"
                            >
                                {localize("cancel")}
                            </Button>
                            <Button
                                disabled={submitting}
                                onClick={async () => {
                                    // 校验顺序：信息源 → 频道名称 → 子频道筛选条件
                                    if (sources.length < 1) {
                                        showToast({
                                            message: localize("need_one_source") || "至少需添加 1 个信息源",
                                            severity: NotificationSeverity.WARNING
                                        });
                                        return;
                                    }
                                    if (!channelName.trim()) {
                                        showToast({
                                            message: localize("cannot_empty_channel_name"),
                                            severity: NotificationSeverity.WARNING
                                        });
                                        return;
                                    }
                                    if (contentFilter) {
                                        const err = validateFilterGroups(filterGroups);
                                        if (err) {
                                            showToast({
                                                message: err,
                                                severity: NotificationSeverity.WARNING
                                            });
                                            return;
                                        }
                                    }
                                    if (createSubChannel) {
                                        for (const sub of subChannels) {
                                            if (!sub.name.trim()) {
                                                showToast({
                                                    message: localize("cannot_subchannel_name"),
                                                    severity: NotificationSeverity.WARNING
                                                });
                                                return;
                                            }
                                            const err = validateFilterGroups(sub.groups);
                                            if (err) {
                                                showToast({
                                                    message: localize("cannot_filter_criteria"),
                                                    severity: NotificationSeverity.WARNING
                                                });
                                                return;
                                            }
                                        }
                                    }
                                    const data: CreateChannelFormData = {
                                        sources,
                                        channelName: channelName.trim(),
                                        channelDesc: channelDesc.trim(),
                                        visibility,
                                        publishToSquare,
                                        contentFilter,
                                        filterGroups,
                                        topFilterRelation,
                                        createSubChannel,
                                        subChannels
                                    };
                                    if (!onConfirm) return;
                                    try {
                                        setSubmitting(true);
                                        const res = await onConfirm(data);
                                        setCreatedChannelId(res.channelId);
                                        setShowSuccess(true);
                                    } catch {
                                        showToast({
                                            message: localize("channel_create_failed") || "频道创建失败，请稍后重试",
                                            severity: NotificationSeverity.ERROR
                                        });
                                    } finally {
                                        setSubmitting(false);
                                    }
                                }}
                                className="h-9 px-5 bg-[#165DFF] hover:bg-[#4080FF] text-white border-none text-[14px] disabled:opacity-50"
                            >
                                {submitting ? (localize("creating") || "创建中...") : (localize("confirm_creation") || "确认创建")}
                            </Button>
                        </div>
                    )}
                </SheetContent>
            </Sheet>

            {/* 唯一弹窗：仅点击「确认爬取」后打开 */}
            <CrawlPreviewDialog
                open={crawlDialogOpen}
                onOpenChange={setCrawlDialogOpen}
                url={crawlUrl}
                onAddSource={(source) => {
                    setSources((prev) => [...prev, source]);
                    setCrawlDialogOpen(false);
                    setShowAddSourcePanel(false);
                }}
            />

            <AlertDialog open={showCancelConfirm} onOpenChange={setShowCancelConfirm}>
                <AlertDialogContent>
                    <AlertDialogHeader>
                        <AlertDialogTitle>{localize("confirm_close")}</AlertDialogTitle>
                        <AlertDialogDescription>
                            {"关闭后将不保存任何数据，返回原页面"}
                        </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                        <AlertDialogCancel>{localize("continue_editing")}</AlertDialogCancel>
                        <AlertDialogAction onClick={confirmClose}>
                            {localize("confirm_close")}
                        </AlertDialogAction>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>
        </>
    );
}

function SubChannelBlock({
    data,
    openInEditMode = false,
    onEditModeOpened,
    onNameChange,
    onRemove,
    onToggleCollapse,
    onGroupsChange,
    onTopRelationChange,
    onOverLimit,
    onEmptyName
}: {
    data: SubChannelData;
    openInEditMode?: boolean;
    onEditModeOpened?: () => void;
    onNameChange: (name: string) => void;
    onRemove: () => void;
    onToggleCollapse: () => void;
    onGroupsChange: (groups: FilterGroup[]) => void;
    onTopRelationChange: (r: FilterRelation) => void;
    onOverLimit?: () => void;
    onEmptyName?: () => void;
}) {
    const [isEditing, setIsEditing] = useState(openInEditMode);
    const [editVal, setEditVal] = useState(data.name);
    const inputRef = useRef<HTMLInputElement>(null);

    useEffect(() => {
        if (openInEditMode && inputRef.current) {
            inputRef.current.focus();
            inputRef.current.select();
            onEditModeOpened?.();
        }
    }, [openInEditMode, onEditModeOpened]);

    const handleSave = () => {
        const v = editVal.trim();
        if (!v) {
            onEmptyName?.();
            return;
        }
        onNameChange(v);
        setIsEditing(false);
    };

    const handleNameChange = (val: string) => {
        if (val.length > MAX_CHANNEL_NAME) {
            onOverLimit?.();
            setEditVal(val.slice(0, MAX_CHANNEL_NAME));
        } else {
            setEditVal(val);
        }
    };

    return (
        <div className="border border-t-[#E5E6EB] overflow-hidden">
            <div className="flex items-center justify-between gap-2 px-3 py-2 bg-[#F7F8FA]">
                <button
                    type="button"
                    onClick={onToggleCollapse}
                    className="p-1 text-[#86909C] hover:text-[#4E5969] flex-shrink-0"
                >
                    {data.collapsed ? (
                        <ChevronRight className="size-4" />
                    ) : (
                        <ChevronDown className="size-4" />
                    )}
                </button>
                {isEditing ? (
                    <input
                        ref={inputRef}
                        value={editVal}
                        onChange={(e) => handleNameChange(e.target.value)}
                        onBlur={handleSave}
                        onKeyDown={(e) => e.key === "Enter" && handleSave()}
                        className="flex-1 min-w-0 px-2 py-1 text-[14px] border border-[#E5E6EB] rounded focus:outline-none focus:ring-1 focus:ring-[#165DFF]"
                        placeholder="子频道名称"
                    />
                ) : (
                    <div
                        className="flex-1 flex items-center gap-1 cursor-pointer group min-w-0"
                        onClick={() => {
                            setEditVal(data.name);
                            setIsEditing(true);
                        }}
                    >
                        <span className="text-[14px] text-[#1D2129] truncate">{data.name}</span>
                        <Pencil className="size-3.5 text-[#86909C] opacity-0 group-hover:opacity-100 flex-shrink-0" />
                    </div>
                )}
                <button
                    type="button"
                    onClick={onRemove}
                    className="flex items-center gap-1 text-[14px] text-[#86909C] hover:text-[#F53F3F] flex-shrink-0"
                >
                    删除
                </button>
            </div>
            {!data.collapsed && (
                <div className="p-3 border-t border-[#E5E6EB]">
                    <FilterConditionEditor
                        groups={data.groups}
                        topRelation={data.topRelation}
                        onGroupsChange={onGroupsChange}
                        onTopRelationChange={onTopRelationChange}
                    />
                </div>
            )}
        </div>
    );
}
