import type { ComponentPropsWithoutRef } from "react";
import { DropdownMenuItem } from "~/components/ui/DropdownMenu";
import { ApprovalLockGuard } from "./ApprovalLockGuard";

interface ApprovalLockMenuItemProps extends ComponentPropsWithoutRef<typeof DropdownMenuItem> {
    locked: boolean;
}

/** Keep the menu accessible while explaining why an individual action is disabled. */
export function ApprovalLockMenuItem({ locked, disabled, ...props }: ApprovalLockMenuItemProps) {
    return (
        <ApprovalLockGuard locked={locked} className="block w-full">
            <DropdownMenuItem
                {...props}
                disabled={locked || disabled}
                onClick={locked ? undefined : props.onClick}
                onSelect={locked ? undefined : props.onSelect}
            />
        </ApprovalLockGuard>
    );
}
