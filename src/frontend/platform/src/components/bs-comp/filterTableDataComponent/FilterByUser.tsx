import { Select } from "@bisheng/ui"
import { getUsersApi } from "@/controllers/API/user"
import { useSubjectSearch } from "../selectComponent/useSubjectSearch"
import { useSelectLabels } from "../formFields/useSelectLabels"
import { useTranslation } from "react-i18next"
import type { User } from "@/types/api/user"

interface UserOption { label: string; value: number }
interface FilterByUserProps {
  value: UserOption[]
  placeholder?: string
  onChange: (value: UserOption[]) => void
}

/** Single-user filter; the business value stays a 0/1-length UserOption[]. */
export default function FilterByUser({ value, placeholder, onChange }: FilterByUserProps) {
  const { t } = useTranslation("bs")
  const selectLabels = useSelectLabels()
  const search = useSubjectSearch<User>({
    delay: 500,
    fetchPage: (keyword, page, signal) => getUsersApi({ name: keyword, page, pageSize: 20 }, { signal }),
  })
  // Retain loaded rows during pagination so the dropdown keeps its scroll position.
  const rows = search.tooLong ? [] : search.rows
  const options = rows
    .filter(user => user.user_id != null)
    .map(user => ({
      label: user.external_id ? `${user.user_name} (${t("subjectSearch.userId")}: ${user.external_id})` : user.user_name,
      value: String(user.user_id),
    }))
  // Keep the selected user's label resolvable when the current search page lacks it
  value.forEach(option => {
    if (!options.some(o => o.value === String(option.value))) options.push({ label: option.label, value: String(option.value) })
  })
  const statusText = search.tooLong
    ? t("subjectSearch.tooLong")
    : search.failed
      ? <>{t("subjectSearch.failed")} <button type="button" onClick={search.retry}>{t("subjectSearch.retry")}</button></>
      : t("subjectSearch.emptyUsers")
  const label = placeholder || t("subjectSearch.userPlaceholder")
  return <Select
    {...selectLabels}
    showSearch
    allowClear
    className="w-[200px]"
    aria-label={label}
    placeholder={label}
    options={options}
    value={value[0] ? String(value[0].value) : null}
    loading={search.loading && rows.length === 0}
    loadingMore={search.loading && rows.length > 0}
    emptyText={statusText}
    noMatchText={statusText}
    onOpenChange={open => { if (open) search.changeKeyword("") }}
    onSearch={search.changeKeyword}
    onLoadMore={search.loadMore}
    onChange={(_value, option) => onChange(option ? [{ label: option.label, value: Number(option.value) }] : [])}
  />
}
