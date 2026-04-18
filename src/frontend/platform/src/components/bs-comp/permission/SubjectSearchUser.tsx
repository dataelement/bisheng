import { Checkbox } from "@/components/bs-ui/checkBox"
import { SearchInput } from "@/components/bs-ui/input"
import { getUsersApi } from "@/controllers/API/user"
import { User as UserIcon } from "lucide-react"
import { useCallback, useEffect, useRef, useState } from "react"
import { useTranslation } from "react-i18next"
import { SelectedSubject } from "./types"

interface SubjectSearchUserProps {
  value: SelectedSubject[]
  onChange: (v: SelectedSubject[]) => void
}

export function SubjectSearchUser({ value, onChange }: SubjectSearchUserProps) {
  const { t } = useTranslation('permission')
  const [keyword, setKeyword] = useState('')
  const [results, setResults] = useState<{ user_id: number; user_name: string }[]>([])
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

  const toggle = (user: { user_id: number; user_name: string }) => {
    if (selectedIds.has(user.user_id)) {
      onChange(value.filter((s) => s.id !== user.user_id))
    } else {
      onChange([...value, { type: 'user', id: user.user_id, name: user.user_name }])
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <SearchInput
        placeholder={t('search.user')}
        value={keyword}
        onChange={handleInput}
      />
      <div className="max-h-[min(320px,50vh)] min-h-[120px] overflow-y-auto overscroll-contain border rounded-md">
        {loading && (
          <div className="py-4 text-center text-sm text-muted-foreground">{t('loading', { ns: 'bs' })}</div>
        )}
        {!loading && results.length === 0 && (
          <div className="py-4 text-center text-sm text-muted-foreground">
            {t('empty.searchResults')}
          </div>
        )}
        {!loading && results.map((user) => (
          <div
            key={user.user_id}
            className="flex items-center gap-2 px-3 py-2 cursor-pointer hover:bg-accent"
            onClick={() => toggle(user)}
          >
            <Checkbox checked={selectedIds.has(user.user_id)} />
            <UserIcon className="h-4 w-4 text-muted-foreground" />
            <span className="text-sm truncate">{user.user_name}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
