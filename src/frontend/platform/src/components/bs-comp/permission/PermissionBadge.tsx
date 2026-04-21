import { Badge } from "@/components/bs-ui/badge"
import { cname } from "@/components/bs-ui/utils"
import { useTranslation } from "react-i18next"
import { RelationLevel } from "./types"

const LEVEL_STYLES: Record<RelationLevel, string> = {
  owner: 'bg-purple-100 text-purple-700 border-purple-200',
  manager: 'bg-blue-100 text-blue-700 border-blue-200',
  editor: 'bg-green-100 text-green-700 border-green-200',
  viewer: 'bg-gray-100 text-gray-700 border-gray-200',
}

interface PermissionBadgeProps {
  level: RelationLevel | null | undefined
  className?: string
}

export function PermissionBadge({ level, className }: PermissionBadgeProps) {
  const { t } = useTranslation('permission')

  if (!level) return null

  return (
    <Badge
      variant="outline"
      className={cname(
        'text-[11px] px-1.5 py-0 font-normal',
        LEVEL_STYLES[level],
        className,
      )}
    >
      {t(`level.${level}`)}
    </Badge>
  )
}
