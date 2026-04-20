import { useLocalize } from "~/hooks";
import type { RelationLevel } from "~/api/permission";
import { cn } from "~/utils";

const LEVEL_STYLES: Record<RelationLevel, string> = {
  owner: "bg-purple-100 text-purple-700 border-purple-200",
  manager: "bg-blue-100 text-blue-700 border-blue-200",
  editor: "bg-green-100 text-green-700 border-green-200",
  viewer: "bg-gray-100 text-gray-700 border-gray-200",
};

interface PermissionBadgeProps {
  level: RelationLevel | null | undefined;
  className?: string;
}

export function PermissionBadge({ level, className }: PermissionBadgeProps) {
  const localize = useLocalize();
  if (!level) return null;

  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md border px-1.5 py-0 text-[11px] font-normal",
        LEVEL_STYLES[level],
        className
      )}
    >
      {localize(`com_permission.level_${level}`)}
    </span>
  );
}
