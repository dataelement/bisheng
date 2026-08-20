import { Outlined } from "bisheng-icons";

import type { FileChangeAction } from "~/api/knowledge";
import { cn } from "~/utils";

/**
 * Leading glyph of the "审批中" pill — one icon per change action, mirroring the
 * icons the row action menu uses for the same operations (Figma 13198:78120).
 */
const ACTION_ICONS: Record<FileChangeAction, typeof Outlined.Upload> = {
    upload: Outlined.Upload,
    rename: Outlined.Edit,
    move: Outlined.MoveToFolder,
    delete: Outlined.Delete,
};

interface FileChangeActionIconProps {
    action: FileChangeAction;
    className?: string;
}

export function FileChangeActionIcon({ action, className }: FileChangeActionIconProps) {
    const Icon = ACTION_ICONS[action];
    if (!Icon) return null;
    return <Icon className={cn("size-3 shrink-0", className)} />;
}
