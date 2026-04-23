import { RelationLevel } from "./types"

interface PermissionBadgeProps {
  level: RelationLevel | null | undefined
  className?: string
}

/** 产品要求：列表/看板等场景不再展示「所有者 / 可编辑」等关系角标，保留组件以兼容旧调用处。 */
export function PermissionBadge(_props: PermissionBadgeProps) {
  return null
}
