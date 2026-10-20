import MultiSelect from "@/components/bs-ui/select/multi"
import { getUsersApi } from "@/controllers/API/user"
import { useSubjectSearch } from "../selectComponent/useSubjectSearch"
import { SubjectSearchStatus } from "../selectComponent/SubjectSearchStatus"
import { useTranslation } from "react-i18next"
import type { User } from "@/types/api/user"

interface UserOption { label: string; value: number }
interface FilterByUserProps {
  value: UserOption[]
  placeholder?: string
  onChange: (value: UserOption[]) => void
}

export default function FilterByUser({ value, placeholder, onChange }: FilterByUserProps) {
  const { t } = useTranslation("bs")
  const search = useSubjectSearch<User>({
    delay: 500,
    fetchPage: (keyword, page, signal) => getUsersApi({ name: keyword, page, pageSize: 20 }, { signal }),
  })
  const options = search.loading || search.failed || search.tooLong ? [] : search.rows.map(user => ({
    label: user.external_id ? `${user.user_name} (${t("subjectSearch.userId")}: ${user.external_id})` : user.user_name,
    value: String(user.user_id),
  }))
  return <div className="w-[200px] relative">
    <MultiSelect contentClassName="overflow-y-auto max-w-[200px] [&_[data-radix-select-viewport]]:min-w-0" options={options} value={value.map(option => ({ ...option, value: String(option.value) }))}
      placeholder={placeholder || t("subjectSearch.userPlaceholder")}
      searchPlaceholder={t("subjectSearch.userPlaceholder")}
      searchInputProps={search.inputProps}
      onLoad={() => search.changeKeyword("")} onScrollLoad={search.loadMore} onChange={options => onChange(options.map(option => ({ ...option, value: Number(option.value) })))}>
      <SubjectSearchStatus tooLong={search.tooLong} failed={search.failed} loading={search.loading} empty={!search.rows.length} onRetry={search.retry} />
    </MultiSelect>
  </div>
}
