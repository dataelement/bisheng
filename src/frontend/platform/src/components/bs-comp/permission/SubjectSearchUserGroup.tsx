import { Checkbox } from '@bisheng/ui';
import { Search, Users } from "lucide-react"
import { getGrantSubjectUserGroupsApi, type GrantSubjectUserGroup } from "@/controllers/API/permission"
import { useTranslation } from "react-i18next"
import { useSubjectSearch } from "../selectComponent/useSubjectSearch"
import { SubjectBusinessId, SubjectSearchStatus } from "../selectComponent/SubjectSearchStatus"
import { ResourceType, SelectedSubject } from "./types"

interface SubjectSearchUserGroupProps {
  value: SelectedSubject[]
  onChange: (value: SelectedSubject[]) => void
  resourceType?: ResourceType
  resourceId?: string
  disabledIds?: number[]
}

export function SubjectSearchUserGroup({ value, onChange, resourceType, resourceId, disabledIds = [] }: SubjectSearchUserGroupProps) {
  const { t } = useTranslation("permission")
  const search = useSubjectSearch<GrantSubjectUserGroup>({
    scopeKey: `${resourceType}:${resourceId}`,
    fetchPage: async (keyword, page, signal) => {
      if (!resourceType || !resourceId) return { data: [], total: 0 }
      return getGrantSubjectUserGroupsApi(resourceType, resourceId, { keyword, page, pageSize: 50 }, { signal })
    },
  })
  const selectedIds = new Set(value.filter(subject => subject.type === "user_group").map(subject => subject.id))
  const disabled = new Set(disabledIds)
  const toggle = (group: GrantSubjectUserGroup) => {
    if (search.loading || search.failed || search.tooLong || disabled.has(group.id)) return
    onChange(selectedIds.has(group.id)
      ? value.filter(subject => subject.type !== "user_group" || subject.id !== group.id)
      : [...value, { type: "user_group", id: group.id, name: group.name, externalId: String(group.id) }])
  }
  return <div className="flex h-full min-h-0 flex-col gap-3">
    <div className="relative shrink-0">
      <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[#999999]" />
      <input type="text" placeholder={t("search.userGroup")} {...search.inputProps} className="h-8 w-full rounded-[6px] border border-[#EBECF0] bg-white pl-9 pr-3 text-[14px] text-[#212121] outline-none transition-colors placeholder:text-[#999999] focus:border-[#C9CDD4]" />
    </div>
    <div className="min-h-0 flex-1 overflow-y-auto rounded-[6px] border border-[#EBECF0]" onScroll={event => {
      const element = event.currentTarget
      if (element.scrollTop + element.clientHeight >= element.scrollHeight - 100) search.loadMore()
    }}>
      <SubjectSearchStatus permission tooLong={search.tooLong} failed={search.failed} loading={search.loading} empty={search.rows.length === 0} onRetry={search.retry} />
      {!search.loading && !search.failed && !search.tooLong && search.rows.map(group => <div key={group.id} className={`flex min-w-0 items-center gap-2 px-3 py-2 ${disabled.has(group.id) ? 'cursor-not-allowed opacity-60' : 'cursor-pointer hover:bg-accent'}`} onClick={() => toggle(group)}>
        <Checkbox className="peer" checked={selectedIds.has(group.id) || disabled.has(group.id)} disabled={disabled.has(group.id)} />
        <Users className="h-4 w-4 shrink-0 text-muted-foreground" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm" title={group.name}>{group.name}</div>
          <SubjectBusinessId kind="user_group" value={String(group.id)} />
        </div>
      </div>)}
      {!search.loading && !search.failed && search.rows.length < search.total && <button type="button" onClick={search.loadMore}>{t("subjectSearch.loadMore", { ns: "bs" })}</button>}
    </div>
  </div>
}
