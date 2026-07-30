import type { ResourceType } from "~/api/permission";
import { PermissionDialog } from "~/components/permission/PermissionDialog";

interface KnowledgeSpaceShareDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  resourceType?: ResourceType;
  resourceId: string;
  resourceName: string;
  isDepartmentSpace?: boolean;
}

export function KnowledgeSpaceShareDialog({
  open,
  onOpenChange,
  resourceType = "knowledge_space",
  resourceId,
  resourceName,
}: KnowledgeSpaceShareDialogProps) {
  return (
    <PermissionDialog
      open={open}
      onOpenChange={onOpenChange}
      resourceType={resourceType}
      resourceId={resourceId}
      resourceName={resourceName}
    />
  );
}
