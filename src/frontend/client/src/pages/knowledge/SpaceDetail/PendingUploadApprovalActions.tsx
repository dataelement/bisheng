import { Button } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";

import { Tooltip, TooltipContent, TooltipTrigger } from "~/components/ui/Tooltip2";
import { useLocalize } from "~/hooks";

interface PendingUploadApprovalActionsProps {
    requestId: number;
    disabled?: boolean;
    /** Approver path: renders the 同意 / 拒绝 buttons. */
    onDecide?: (requestId: number, action: "approve" | "reject") => void;
    /** Applicant path: renders a single 撤回 button for the viewer's own request. */
    onWithdraw?: (requestId: number) => void;
}

export function PendingUploadApprovalActions({
    requestId,
    disabled = false,
    onDecide,
    onWithdraw,
}: PendingUploadApprovalActionsProps) {
    const localize = useLocalize();
    const approveLabel = localize("com_approval_action_approve");
    const rejectLabel = localize("com_approval_action_reject");
    const withdrawLabel = localize("com_approval_action_withdraw");

    return (
        <div className="flex shrink-0 items-center gap-1">
            {onDecide && (
                <>
                    <Tooltip>
                        <TooltipTrigger asChild>
                            <Button
                                color="default"
                                variant="text"
                                size="small"
                                iconOnly
                                className="text-success hover:text-success"
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
                    <Tooltip>
                        <TooltipTrigger asChild>
                            <Button
                                color="danger"
                                variant="text"
                                size="small"
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
                            size="small"
                            iconOnly
                            aria-label={withdrawLabel}
                            disabled={disabled}
                            onClick={(event) => {
                                event.stopPropagation();
                                onWithdraw(requestId);
                            }}
                        >
                            <Outlined.CloseCircle className="size-4" />
                        </Button>
                    </TooltipTrigger>
                    <TooltipContent>{withdrawLabel}</TooltipContent>
                </Tooltip>
            )}
        </div>
    );
}
