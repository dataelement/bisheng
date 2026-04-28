import { Channel } from "~/api/channels";
import { ChannelMemberManagementPanel } from "~/components/ChannelMemberManagementPanel";
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
} from "~/components/ui";
import { useLocalize } from "~/hooks";

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
    const localize = useLocalize();

    if (!channel) return null;

    const resourceName = channel.name ? ` - ${channel.name}` : "";

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent
                className="!flex h-[80vh] max-h-[800px] w-[calc(100vw-80px)] max-w-[800px] min-w-0 flex-col gap-0 overflow-hidden p-5 max-[768px]:fixed max-[768px]:inset-0 max-[768px]:h-[100dvh] max-[768px]:max-h-[100dvh] max-[768px]:w-full max-[768px]:max-w-none max-[768px]:translate-x-0 max-[768px]:translate-y-0 max-[768px]:rounded-none max-[768px]:p-4"
                onOpenAutoFocus={(e) => e.preventDefault()}
            >
                <DialogHeader className="shrink-0 text-left">
                    <DialogTitle className="text-left">
                        {localize("com_subscription.management_member")}{resourceName}
                    </DialogTitle>
                </DialogHeader>

                <div className="mt-4 flex min-h-0 flex-1 flex-col overflow-hidden">
                    <ChannelMemberManagementPanel
                        channelId={channel.id}
                        currentUserRole={channel.role}
                        active={open}
                    />
                </div>
            </DialogContent>
        </Dialog>
    );
}
