import { Checkbox } from "@/components/bs-ui/checkBox"
import { SearchInput } from "@/components/bs-ui/input"
import { getUsersApi } from "@/controllers/API/user"
import { User as UserIcon } from "lucide-react"
import { useCallback, useEffect, useRef, useState } from "react"
import { useTranslation } from "react-i18next"
import { SelectedSubject } from "./types"

type UserSearchResult = {
  user_id: number
  user_name: string
  person_id?: string | null
  external_id?: string | null
  department_path?: string | null
  primary_department_path?: string | null
}

interface SubjectSearchUserProps {
  value: SelectedSubject[]
  onChange: (v: SelectedSubject[]) => void
}

export function SubjectSearchUser({ value, onChange }: SubjectSearchUserProps) {
  const { t } = useTranslation('permission')
  const [keyword, setKeyword] = useState('')
  const [results, setResults] = useState<UserSearchResult[]>([])
  const [loading, setLoading] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const search = useCallback(async (name: string) => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setLoading(true)
    try {
      // 与后端部门子树/用户组并集后的结果量可能较大；单次多取避免只看到第一页
      const res = await getUsersApi(
        { name, page: 1, pageSize: 200 },
        { signal: controller.signal },
      )
      if (!controller.signal.aborted) {
        setResults(res.data || [])
      }
    } catch {
      // Abort or network error — ignore
    } finally {
      if (!controller.signal.aborted) {
        setLoading(false)
      }
    }
  }, [])

  useEffect(() => {
    // Initial load
    search('')
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
      abortRef.current?.abort()
    }
  }, [search])

  const handleInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value
    setKeyword(val)
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => search(val), 300)
  }

  const selectedIds = new Set(value.map((s) => s.id))

  const toggle = (user: UserSearchResult) => {
    if (selectedIds.has(user.user_id)) {
      onChange(value.filter((s) => s.id !== user.user_id))
    } else {
      onChange([...value, { type: 'user', id: user.user_id, name: user.user_name }])
    }
  }

  return (
    <div className="flex min-h-0 flex-col gap-2">
      <SearchInput
        placeholder={t('search.user')}
        value={keyword}
        onChange={handleInput}
      />
      <div className="min-h-[120px] max-h-[clamp(120px,calc(100vh-24rem),320px)] overflow-y-auto overscroll-contain rounded-md border">
        {loading && (
          <div className="py-4 text-center text-sm text-muted-foreground">{t('loading', { ns: 'bs' })}</div>
        )}
        {!loading && results.length === 0 && (
          <div className="py-4 text-center text-sm text-muted-foreground">
            {t('empty.searchResults')}
          </div>
        )}
        {!loading && results.map((user) => {
          const personId = user.person_id || user.external_id
          const departmentPath = user.department_path || user.primary_department_path
          return (
            <div
              key={user.user_id}
              className="flex min-w-0 cursor-pointer items-center gap-2 px-3 py-2 hover:bg-accent"
              onClick={() => toggle(user)}
            >
              <Checkbox checked={selectedIds.has(user.user_id)} />
              <UserIcon className="h-4 w-4 shrink-0 text-muted-foreground" />
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm" title={user.user_name}>{user.user_name}</div>
                {(personId || departmentPath) && (
                  <div
                    className="truncate text-xs text-muted-foreground"
                    title={[personId, departmentPath].filter(Boolean).join(" / ")}
                  >
                    {[personId, departmentPath].filter(Boolean).join(" / ")}
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
