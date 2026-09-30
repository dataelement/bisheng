import { TipIcon } from "@/components/bs-icons"
import type { ApiKeyItem } from "@/types/api/openApi"
import { useTranslation } from "react-i18next"
import { summarizeGrantKeys } from "./resourceGrantUtils"

export interface GrantScopeNoticeProps {
  keys: ApiKeyItem[]
}

/**
 * Tells the administrator whether this grant list matters at all.
 *
 * Grants only constrain keys that call as the service account itself. A key
 * with 「代表用户调用」 is judged by the represented user's own permissions, so
 * the list below is irrelevant to it. The notice picks one of four wordings
 * from the current mix of valid keys.
 */
export function GrantScopeNotice({ keys }: GrantScopeNoticeProps) {
  const { t } = useTranslation()
  const { own, delegate } = summarizeGrantKeys(keys)

  let title: string
  let description: string
  if (own + delegate === 0) {
    title = t("openApiManagement.grants.notice.noKeyTitle")
    description = t("openApiManagement.grants.notice.noKeyDesc")
  } else if (own === 0) {
    title = t("openApiManagement.grants.notice.delegateOnlyTitle")
    description = t("openApiManagement.grants.notice.delegateOnlyDesc")
  } else if (delegate === 0) {
    title = t("openApiManagement.grants.notice.ownOnlyTitle")
    description = t("openApiManagement.grants.notice.scopeRule")
  } else {
    title = t("openApiManagement.grants.notice.mixedTitle", { count: own })
    description = `${t("openApiManagement.grants.notice.mixedDesc", {
      count: delegate,
    })}${t("openApiManagement.grants.notice.scopeRule")}`
  }

  return (
    <div className="flex gap-2 rounded-md border bg-muted/30 p-4">
      <TipIcon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
      <div className="min-w-0 space-y-1">
        <p className="text-sm font-medium">{title}</p>
        <p className="text-sm text-muted-foreground">{description}</p>
      </div>
    </div>
  )
}
