import { Checkbox } from "@/components/bs-ui/checkBox"
import { getResourceGrantUserGroupsApi } from "@/controllers/API/permission"
import { getUserGroupsApi } from "@/controllers/API/user"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { Search, Users } from "lucide-react"
import { useEffect, useMemo, useState } from "react"
import { useTranslation } from "react-i18next"
import { ResourceType, SelectedSubject } from "./types"

interface UserGroup {
  id: number
  group_name: string
}

interface SubjectSearchUserGroupProps {
  value: SelectedSubject[]
  onChange: (v: SelectedSubject[]) => void
  resourceType?: ResourceType
  resourceId?: string
  disabledIds?: number[]
}

export function SubjectSearchUserGroup({
  value,
  onChange,
  resourceType,
  resourceId,
  disabledIds = [],
}: SubjectSearchUserGroupProps) {
  const { t } = useTranslation('permission')
  const [groups, setGroups] = useState<UserGroup[]>([])
  const [loading, setLoading] = useState(false)
  const [keyword, setKeyword] = useState('')

  useEffect(() => {
    setLoading(true)
    const request = resourceType && resourceId
      ? getResourceGrantUserGroupsApi(resourceType, resourceId)
      : getUserGroupsApi({})
    captureAndAlertRequestErrorHoc(request).then((res) => {
      if (res) setGroups(Array.isArray(res) ? res : [])
      setLoading(false)
    })
  }, [resourceId, resourceType])

  const filtered = useMemo(() => {
    if (!keyword) return groups
    const lower = keyword.toLowerCase()
    return groups.filter((g) => g.group_name.toLowerCase().includes(lower))
  }, [groups, keyword])

  const selectedIds = new Set(value.map((s) => s.id))
  const disabledIdSet = new Set(disabledIds)

  const toggle = (group: UserGroup) => {
    if (disabledIdSet.has(group.id)) return
    if (selectedIds.has(group.id)) {
      onChange(value.filter((s) => s.id !== group.id))
    } else {
      onChange([...value, { type: 'user_group', id: group.id, name: group.group_name }])
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <div className="relative shrink-0">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[#999999]" />
        <input
          type="text"
          placeholder={t('search.userGroup')}
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          className="h-8 w-full rounded-[6px] border border-[#EBECF0] bg-white pl-9 pr-3 text-[14px] text-[#212121] outline-none transition-colors placeholder:text-[#999999] focus:border-[#C9CDD4]"
        />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto rounded-[6px] border border-[#EBECF0]">
        {loading && (
          <div className="py-4 text-center text-sm text-muted-foreground">{t('loading', { ns: 'bs' })}</div>
        )}
        {!loading && filtered.length === 0 && (
          <div className="py-4 text-center text-sm text-muted-foreground">
            {t('empty.userGroups')}
          </div>
        )}
        {!loading && filtered.map((group) => (
          <div
            key={group.id}
            className={`flex min-w-0 items-center gap-2 px-3 py-2 ${
              disabledIdSet.has(group.id)
                ? 'cursor-not-allowed opacity-60'
                : 'cursor-pointer hover:bg-accent'
            }`}
            onClick={() => toggle(group)}
          >
            <Checkbox
              checked={selectedIds.has(group.id) || disabledIdSet.has(group.id)}
              disabled={disabledIdSet.has(group.id)}
            />
            <Users className="h-4 w-4 shrink-0 text-muted-foreground" />
            <span className="min-w-0 truncate text-sm" title={group.group_name}>{group.group_name}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
