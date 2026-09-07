import type { ReactNode } from "react";
import { Tooltip, TooltipContent, TooltipTrigger } from "~/components/ui/Tooltip2";
import cn from "~/utils/cn";
import { KNOWLEDGE_FILE_APPROVAL_LOCK_TOAST } from "../knowledgeUtils";
import styles from "./ApprovalLockGuard.module.css";

interface ApprovalLockGuardProps {
    locked: boolean;
    className?: string;
    children: ReactNode;
}

/** Disabled controls delegate pointer events to this wrapper for a local tooltip. */
export function ApprovalLockGuard({ locked, className, children }: ApprovalLockGuardProps) {
    if (!locked) return <>{children}</>;
    return (
        <Tooltip delayDuration={200} disableHoverableContent>
            <TooltipTrigger asChild>
                <span
                    className={cn("inline-flex", styles.locked, className)}
                    tabIndex={0}
                    aria-disabled="true"
                    onClickCapture={(event) => {
                        event.preventDefault();
                        event.stopPropagation();
                    }}
                >
                    {children}
                </span>
            </TooltipTrigger>
            <TooltipContent side="top" sideOffset={6}>
                {KNOWLEDGE_FILE_APPROVAL_LOCK_TOAST}
            </TooltipContent>
        </Tooltip>
    );
}
