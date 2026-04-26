import type { ResourceType } from "~/api/permission";
import { KnowledgeSpaceShareDialog } from "~/pages/knowledge/SpaceDetail/KnowledgeSpaceShareDialog";

interface PermissionDialogProps {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  resourceType: ResourceType;
  resourceId: string;
  resourceName: string;
}

export function PermissionDialog({
  open,
  onOpenChange,
  resourceType,
  resourceId,
  resourceName,
}: PermissionDialogProps) {
  return (
    <KnowledgeSpaceShareDialog
      open={open}
      onOpenChange={onOpenChange}
      resourceType={resourceType}
      resourceId={resourceId}
      resourceName={resourceName}
      currentUserRole={null}
      showShareTab={false}
      showMembersTab={false}
      showPermissionTab
    />
  );
}
