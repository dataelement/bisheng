import { useTranslation } from "react-i18next"

interface SubjectSearchStatusProps {
  tooLong?: boolean
  failed?: boolean
  loading?: boolean
  empty?: boolean
  permission?: boolean
  onRetry?: () => void
}

export function SubjectSearchStatus({ tooLong, failed, loading, empty, permission, onRetry }: SubjectSearchStatusProps) {
  const { t } = useTranslation("bs")
  if (!tooLong && !failed && !loading && !empty) return null
  return <div className="py-4 text-center text-sm text-muted-foreground" role="status">
    {tooLong ? t("subjectSearch.tooLong") : failed ? <>{t("subjectSearch.failed")} <button type="button" onClick={onRetry}>{t("subjectSearch.retry")}</button></> : loading ? t("loading") : t(permission ? "subjectSearch.emptySubjects" : "subjectSearch.emptyUsers")}
  </div>
}

interface SubjectBusinessIdProps { value?: string | null; kind?: "user" | "department" | "user_group" }
export function SubjectBusinessId({ value, kind = "user" }: SubjectBusinessIdProps) {
  const { t } = useTranslation("bs")
  if (!value) return null
  return <span className="text-xs text-muted-foreground select-text" title={value} onClick={event => { event.stopPropagation(); event.preventDefault() }} onPointerDown={event => event.stopPropagation()}>{t(`subjectSearch.${kind}Id`)}: {value}</span>
}
