import type { PermissionGrantSource } from "@/controllers/API/permission"
import { Building2, GitBranch, UserRound, UsersRound } from "lucide-react"
import { useTranslation } from "react-i18next"

interface SourceBadgeProps {
  source: PermissionGrantSource
}

const SOURCE_ICONS = {
  direct: UserRound,
  department: Building2,
  user_group: UsersRound,
  inherited: GitBranch,
}

export function SourceBadge({ source }: SourceBadgeProps) {
  const { t } = useTranslation("permission")
  const normalizedType = source.type.toLowerCase()
  const SourceIcon =
    SOURCE_ICONS[normalizedType as keyof typeof SOURCE_ICONS] ?? GitBranch

  return (
    <span
      data-source-type={source.type}
      className="inline-flex items-center gap-1 rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-800"
    >
      <SourceIcon aria-hidden="true" className="size-3" />
      {t(`source.${normalizedType}`)}
      {source.include_children && (
        <span className="font-normal">· {t("source.includeChildren")}</span>
      )}
      {source.userset_relation === "admin" && (
        <span className="font-normal">· {t("source.userGroupAdmin")}</span>
      )}
    </span>
  )
}
