import { Button } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";

import { Tooltip, TooltipContent, TooltipTrigger } from "~/components/ui/Tooltip2";
import { useLocalize } from "~/hooks";
import { cn } from "~/utils";

interface PendingUploadApprovalActionsProps {
    requestId: number;
    disabled?: boolean;
    /** Approver path: renders the 同意 / 拒绝 buttons. */
    onDecide?: (requestId: number, action: "approve" | "reject") => void;
    /** Applicant path: renders a single 删除 button for the viewer's own request.
     *  Implemented as an approval withdrawal, but to the applicant it is just a
     *  delete — the file disappears either way — so it is named and styled like
     *  every other delete and confirms the same way. */
    onWithdraw?: (requestId: number) => void;
    /** Hover fill for the neutral (同意) button, supplied by the row so it can
     *  react to the row's own background — a selected row needs the button to
     *  lift towards white rather than sink into another grey step. The danger
     *  buttons keep their own red tint. */
    hoverClassName?: string;
}

export function PendingUploadApprovalActions({
    requestId,
    disabled = false,
    onDecide,
    onWithdraw,
    hoverClassName,
}: PendingUploadApprovalActionsProps) {
    const localize = useLocalize();
    // 同意 (not 审批中心's 通过) per the pending-upload design (Figma 13198:78124).
    const approveLabel = localize("com_approval.action_approve");
    const rejectLabel = localize("com_approval.action_reject");
    const withdrawLabel = localize("com_knowledge.delete");

    // No gap: these sit in the same row-action strip as 下载 / 更多, which are
    // flush 32x32 slots — `size="medium"` + iconOnly matches them exactly.
    return (
        <div className="flex shrink-0 items-center">
            {onDecide && (
                <>
                    <Tooltip>
                        <TooltipTrigger asChild>
                            <Button
                                color="default"
                                variant="text"
                                size="medium"
                                iconOnly
                                className={cn("rounded-lg text-success hover:text-success", hoverClassName)}
                                aria-label={approveLabel}
                                disabled={disabled}
                                onClick={(event) => {
                                    event.stopPropagation();
                                    onDecide(requestId, "approve");
                                }}
                            >
                                <Outlined.Check className="size-4" />
                            </Button>
                        </TooltipTrigger>
                        <TooltipContent>{approveLabel}</TooltipContent>
                    </Tooltip>
                    {/* Same hairline separator the 下载 / 更多 pair uses. */}
                    <span aria-hidden className="mx-1 h-2 w-px shrink-0 bg-border-base" />
                    <Tooltip>
                        <TooltipTrigger asChild>
                            <Button
                                color="danger"
                                variant="text"
                                className="rounded-lg"
                                size="medium"
                                iconOnly
                                aria-label={rejectLabel}
                                disabled={disabled}
                                onClick={(event) => {
                                    event.stopPropagation();
                                    onDecide(requestId, "reject");
                                }}
                            >
                                <Outlined.Close className="size-4" />
                            </Button>
                        </TooltipTrigger>
                        <TooltipContent>{rejectLabel}</TooltipContent>
                    </Tooltip>
                </>
            )}
            {onWithdraw && (
                <Tooltip>
                    <TooltipTrigger asChild>
                        <Button
                            color="danger"
                            variant="text"
                            className="rounded-lg"
                            size="medium"
                            iconOnly
                            aria-label={withdrawLabel}
                            disabled={disabled}
                            onClick={(event) => {
                                event.stopPropagation();
                                onWithdraw(requestId);
                            }}
                        >
                            <Outlined.Delete className="size-4" />
                        </Button>
                    </TooltipTrigger>
                    <TooltipContent>{withdrawLabel}</TooltipContent>
                </Tooltip>
            )}
        </div>
    );
}
