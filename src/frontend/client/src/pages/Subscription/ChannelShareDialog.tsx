import { Channel } from "~/api/channels";
import { ChannelPermissionDialog } from "./ChannelPermissionDialog";

interface ChannelShareDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    channel: Channel | null;
}

export function ChannelShareDialog({
    open,
    onOpenChange,
    channel,
}: ChannelShareDialogProps) {
    return (
        <ChannelPermissionDialog
            open={open}
            onOpenChange={onOpenChange}
            channel={channel}
        />
    );
}
