import type { ApiKeyItem } from "@/types/api/openApi"
import { useTranslation } from "react-i18next"
import { splitGrantKeys } from "./resourceGrantUtils"

export interface GrantScopeNoticeProps {
  keys: ApiKeyItem[]
}

/**
 * Names the keys this grant list applies to.
 *
 * Grants only constrain keys that call as the service account itself. A key
 * with 「代表用户调用」 is judged by the represented user's own permissions, so
 * it is listed separately as not using these grants.
 */
export function GrantScopeNotice({ keys }: GrantScopeNoticeProps) {
  const { t } = useTranslation()
  const { own, delegate } = splitGrantKeys(keys)

  if (!own.length && !delegate.length) {
    return (
      <p className="rounded-md border bg-muted/30 px-4 py-3 text-sm text-muted-foreground">
        {t("openApiManagement.grants.notice.noKey")}
      </p>
    )
  }

  return (
    <dl className="grid grid-cols-[auto_1fr] items-start gap-x-4 gap-y-2 rounded-md border bg-muted/30 px-4 py-3 text-sm">
      <dt className="leading-6 text-muted-foreground">
        {t("openApiManagement.grants.notice.appliesTo")}
      </dt>
      <dd>
        <KeyNames keys={own} />
      </dd>
      {delegate.length ? (
        <>
          <dt className="leading-6 text-muted-foreground">
            {t("openApiManagement.grants.notice.notAppliesTo")}
          </dt>
          <dd className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <KeyNames keys={delegate} />
            <span className="text-xs text-muted-foreground">
              {t("openApiManagement.grants.notice.delegateReason")}
            </span>
          </dd>
        </>
      ) : null}
    </dl>
  )
}

function KeyNames({ keys }: { keys: ApiKeyItem[] }) {
  const { t } = useTranslation()
  if (!keys.length) {
    return (
      <span className="leading-6 text-muted-foreground">
        {t("openApiManagement.grants.notice.none")}
      </span>
    )
  }
  return (
    <span className="flex flex-wrap gap-1 py-0.5">
      {keys.map((key) => (
        <span
          key={key.id}
          className="max-w-full break-words rounded bg-muted px-1.5 py-0.5 text-xs"
        >
          {key.name || key.key_mask}
        </span>
      ))}
    </span>
  )
}
