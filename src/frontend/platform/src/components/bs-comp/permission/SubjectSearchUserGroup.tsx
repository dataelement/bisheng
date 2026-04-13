import { Checkbox } from "@/components/bs-ui/checkBox"
import { SearchInput } from "@/components/bs-ui/input"
import { getUserGroupsApi } from "@/controllers/API/user"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { Users } from "lucide-react"
import { useEffect, useMemo, useState } from "react"
import { useTranslation } from "react-i18next"
import { SelectedSubject } from "./types"

interface UserGroup {
  id: number
  group_name: string
}

interface SubjectSearchUserGroupProps {
  value: SelectedSubject[]
  onChange: (v: SelectedSubject[]) => void
}

export function SubjectSearchUserGroup({ value, onChange }: SubjectSearchUserGroupProps) {
  const { t } = useTranslation('permission')
  const [groups, setGroups] = useState<UserGroup[]>([])
  const [loading, setLoading] = useState(false)
  const [keyword, setKeyword] = useState('')

  useEffect(() => {
    setLoading(true)
    captureAndAlertRequestErrorHoc(getUserGroupsApi({})).then((res) => {
      if (res) setGroups(Array.isArray(res) ? res : [])
      setLoading(false)
    })
  }, [])

  const filtered = useMemo(() => {
    if (!keyword) return groups
    const lower = keyword.toLowerCase()
    return groups.filter((g) => g.group_name.toLowerCase().includes(lower))
  }, [groups, keyword])

  const selectedIds = new Set(value.map((s) => s.id))

  const toggle = (group: UserGroup) => {
    if (selectedIds.has(group.id)) {
      onChange(value.filter((s) => s.id !== group.id))
    } else {
      onChange([...value, { type: 'user_group', id: group.id, name: group.group_name }])
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <SearchInput
        placeholder={t('search.userGroup')}
        value={keyword}
        onChange={(e) => setKeyword(e.target.value)}
      />
      <div className="max-h-[200px] overflow-y-auto border rounded-md">
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
            className="flex items-center gap-2 px-3 py-2 cursor-pointer hover:bg-accent"
            onClick={() => toggle(group)}
          >
            <Checkbox checked={selectedIds.has(group.id)} />
            <Users className="h-4 w-4 text-muted-foreground" />
            <span className="text-sm truncate">{group.group_name}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
