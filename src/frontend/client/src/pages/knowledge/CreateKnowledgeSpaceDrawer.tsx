import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import * as RadioGroup from "@radix-ui/react-radio-group";
import { NotificationSeverity } from "~/common";
import { useConfirm, useToastContext } from "~/Providers";
import { Button } from "~/components/ui/Button";
import { Input } from "~/components/ui/Input";
import { Label } from "~/components/ui/Label";
import {
    Sheet,
    SheetContent,
    SheetHeader,
    SheetTitle
} from "~/components/ui/Sheet";
import { Textarea } from "~/components/ui/Textarea";
import { useLocalize } from "~/hooks";
import { KnowledgeSpace, VisibilityType } from "~/api/knowledge";
import { ChannelSuccessIcon } from "~/components/icons/channels";

const MAX_SPACE_NAME = 20;
const MAX_SPACE_DESC = 200;

/** 权限项文案：PingFang SC / 14px / 22px 行高 / 400 / #212121 */
const PERMISSION_OPTION_TEXT_CLASS =
    "text-[14px] font-normal leading-[22px] tracking-normal text-[#212121]";
const PERMISSION_OPTION_FONT: CSSProperties = {
    fontFamily: '"PingFang SC", "PingFang TC", -apple-system, BlinkMacSystemFont, "Helvetica Neue", sans-serif',
};

export type JoinPolicy = "private" | "review" | "public";
export type PublishToSquare = "yes" | "no";

export interface CreateKnowledgeSpaceFormData {
    name: string;
    description: string;
    joinPolicy: JoinPolicy;
    publishToSquare: PublishToSquare;
}

interface CreateKnowledgeSpaceDrawerProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    onConfirm?: (data: CreateKnowledgeSpaceFormData) => void;
    onViewSpace?: () => void;
    onManageMembers?: () => void;
    mode?: "create" | "edit";
    editingSpace?: KnowledgeSpace | null;
}

export function CreateKnowledgeSpaceDrawer({
    open,
    onOpenChange,
    onConfirm,
    onViewSpace,
    onManageMembers,
    mode = "create",
    editingSpace,
}: CreateKnowledgeSpaceDrawerProps) {
    const { showToast } = useToastContext();
    const confirm = useConfirm();
    const localize = useLocalize();
    const [name, setName] = useState("");
    const [description, setDescription] = useState("");
    const [joinPolicy, setJoinPolicy] = useState<JoinPolicy>("review");
    const [publishToSquare, setPublishToSquare] = useState<PublishToSquare>("yes");
    const [showSuccess, setShowSuccess] = useState(false);
    /** Skip max-length enforcement while IME is composing (e.g. Chinese pinyin), so intermediate input is not mistaken as overflow. */
    const nameComposingRef = useRef(false);
    const descComposingRef = useRef(false);

    const needPublishOption = useMemo(
        () => joinPolicy === "review" || joinPolicy === "public",
        [joinPolicy]
    );

    const resetForm = () => {
        setName("");
        setDescription("");
        setJoinPolicy("review");
        setPublishToSquare("yes");
        setShowSuccess(false);
    };

    // Pre-fill form in edit mode
    useEffect(() => {
        if (!open) {
            resetForm();
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
            setShowSuccess(false);
        }
    }, [open, mode, editingSpace]);

    const handleConfirm = () => {
        if (!name.trim()) {
            showToast({
                message: localize("com_subscription.knowledge_space_name_empty") || localize("com_knowledge.space_name_empty"),
                severity: NotificationSeverity.WARNING
            });
            return;
        }
        const payload: CreateKnowledgeSpaceFormData = {
            name: name.trim(),
            description: description.trim(),
            joinPolicy,
            publishToSquare: needPublishOption ? publishToSquare : "no"
        };
        onConfirm?.(payload);
        // Only show success page in create mode
        if (mode === "create") {
            setShowSuccess(true);
        } else {
            onOpenChange(false);
        }
    };
    return (
        <Sheet open={open} onOpenChange={onOpenChange}>
            <SheetContent side="right" className="min-w-[1000px] p-0 bg-white">
                <SheetHeader className="px-8 pt-7 pb-4 border-b border-[#E5E6EB]">
                    <SheetTitle className="text-[20px] font-medium text-[#1D2129] leading-none">
                        {mode === "edit" ? localize("com_subscription.edit_knowledge_space") || localize("com_knowledge.edit_space") : localize("com_subscription.create_konwledge_space")}
                    </SheetTitle>
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
                                    {localize("com_subscription.member_management")}
                                </Button>
                            </div>
                        </div>
                    </div>
                ) : (
                    <div className="flex-1 overflow-y-auto px-8 py-7">
                        <div className="space-y-7">
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
                                            if (v.length > MAX_SPACE_NAME) {
                                                showToast({
                                                    message: localize("com_subscription.max_knowledge_space_name") || localize("com_knowledge.max_20_chars"),
                                                    severity: NotificationSeverity.WARNING
                                                });
                                                setName(v.slice(0, MAX_SPACE_NAME));
                                            }
                                        }}
                                        onChange={(e) => {
                                            const v = e.target.value;
                                            if (nameComposingRef.current) {
                                                setName(v);
                                                return;
                                            }
                                            if (v.length > MAX_SPACE_NAME) {
                                                showToast({
                                                    message: localize("com_subscription.max_knowledge_space_name") || localize("com_knowledge.max_20_chars"),
                                                    severity: NotificationSeverity.WARNING
                                                });
                                                setName(v.slice(0, MAX_SPACE_NAME));
                                            } else {
                                                setName(v);
                                            }
                                        }}
                                        placeholder={localize("com_subscription.enter_knowledge_space_name")}
                                        className="h-11 border-[#E5E6EB] text-[14px] pr-16 bg-[#fff]"
                                    />
                                    <span className="absolute right-4 text-[12px] text-[#86909C]">
                                        {name.length}/{MAX_SPACE_NAME}
                                    </span>
                                </div>
                            </div>

                            {/* 简介 */}
                            <div className="space-y-2">
                                <Label className="text-sm text-[#1D2129] font-medium">
                                    {localize("description")}
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
                                            if (v.length > MAX_SPACE_DESC) {
                                                showToast({
                                                    message: localize("com_subscription.max_knowledge_space_desc") || localize("com_knowledge.max_200_chars"),
                                                    severity: NotificationSeverity.WARNING
                                                });
                                                setDescription(v.slice(0, MAX_SPACE_DESC));
                                            }
                                        }}
                                        onChange={(e) => {
                                            const v = e.target.value;
                                            if (descComposingRef.current) {
                                                setDescription(v);
                                                return;
                                            }
                                            if (v.length > MAX_SPACE_DESC) {
                                                showToast({
                                                    message: localize("com_subscription.max_knowledge_space_desc") || localize("com_knowledge.max_200_chars"),
                                                    severity: NotificationSeverity.WARNING
                                                });
                                                setDescription(v.slice(0, MAX_SPACE_DESC));
                                            } else {
                                                setDescription(v);
                                            }
                                        }}
                                        placeholder={localize("com_subscription.enter_knowledge_space_description")}
                                        className="min-h-[104px] rounded-[6px] border-[#E5E6EB] bg-[#fff] text-[14px]"
                                    />
                                </div>
                            </div>

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
                                            label: localize("publice"),
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
                                                <span className="text-[14px] font-normal text-[#999]">
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
                                        {localize("com_knowledge.publish_to_square")}<span className="ml-2 text-[14px] font-normal text-[#999999]">
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
                        </div>
                    </div>
                )}

                {!showSuccess && (
                    <div className="px-6 py-3 border-t border-[#E5E6EB] flex items-center justify-end gap-2 bg-white">
                        <Button
                            variant="secondary"
                            className="h-8 rounded-[6px] border border-[#E5E6EB] bg-white text-[14px] font-normal text-[#4E5969]"
                            onClick={() => onOpenChange(false)}
                        >
                            {localize("com_knowledge.cancel")}</Button>
                        <Button
                            className="h-8 rounded-[6px] bg-[#165DFF] hover:bg-[#4080FF] text-[14px] font-normal text-white"
                            onClick={handleConfirm}
                        >
                            {mode === "edit" ? localize("com_knowledge.save") : localize("com_knowledge.confirm_create")}
                        </Button>
                    </div>
                )}
            </SheetContent>
        </Sheet>
    );
}

