import { Checkbox } from "@/components/bs-ui/checkBox"
import { SearchInput } from "@/components/bs-ui/input"
import { getResourceGrantUserGroupsApi } from "@/controllers/API/permission"
import { getUserGroupsApi } from "@/controllers/API/user"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { Users } from "lucide-react"
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
    <div className="flex min-h-0 flex-col gap-2">
      <SearchInput
        placeholder={t('search.userGroup')}
        value={keyword}
        onChange={(e) => setKeyword(e.target.value)}
      />
      <div className="min-h-[120px] max-h-[clamp(120px,calc(100vh-24rem),260px)] overflow-y-auto rounded-md border">
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
