import type { Channel } from "~/api/channels";
import { PermissionDialog } from "~/components/permission/PermissionDialog";

interface ChannelPermissionDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  channel: Channel | null;
}

export function ChannelPermissionDialog({
  open,
  onOpenChange,
  channel,
}: ChannelPermissionDialogProps) {
  if (!channel) return null;

  return (
    <PermissionDialog
      open={open}
      onOpenChange={onOpenChange}
      resourceType="channel"
      resourceId={channel.id}
      resourceName={channel.name}
    />
  );
}
