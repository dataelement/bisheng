import type { RelationLevel } from "~/api/permission";

interface PermissionBadgeProps {
  level: RelationLevel | null | undefined;
  className?: string;
}

/** 列表等场景不展示权限关系角标；保留组件以兼容调用处。 */
export function PermissionBadge(_props: PermissionBadgeProps) {
  return null;
}
