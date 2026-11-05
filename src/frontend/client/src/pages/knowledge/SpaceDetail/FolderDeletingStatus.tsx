import { Loader2 } from "lucide-react";
import type { SyntheticEvent } from "react";
import { Tag } from "@bisheng/ui";
import { NotificationSeverity } from "~/common";
import { useLocalize } from "~/hooks";
import { useToastContext } from "~/Providers";

interface FolderDeletingStatusProps {
    state?: "running" | "unknown";
}

export function FolderDeletingStatus({ state = "running" }: FolderDeletingStatusProps) {
    const localize = useLocalize();
    return <Tag size="small" color="default" icon={state === "running" ? <Loader2 className="size-3 animate-spin" /> : undefined}><span role="status">{localize(state === "unknown" ? "com_knowledge.folder_deletion_unknown" : "com_knowledge.folder_deleting")}</span></Tag>;
}

export function useDeletingItemEvents(deleting?: boolean) {
    const localize = useLocalize();
    const { showToast } = useToastContext();
    const block = (event: SyntheticEvent) => {
        if (!deleting) return;
        event.preventDefault();
        event.stopPropagation();
        showToast({ message: localize("com_knowledge.folder_deleting_blocked"), severity: NotificationSeverity.WARNING });
    };
    return { onClickCapture: block, onContextMenuCapture: block, onDragStartCapture: block, onDropCapture: block };
}
