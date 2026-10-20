import { useCallback, useEffect, useRef, useState, type ChangeEvent, type CompositionEvent, type ClipboardEvent } from "react"

export function normalizeSubjectKeyword(value: string): string {
  return value.replace(/\r\n|[\r\n]/g, " ").replace(/^[\u0009-\u000D\u0020\u0085\u00A0\u1680\u2000-\u200A\u2028\u2029\u202F\u205F\u3000]+|[\u0009-\u000D\u0020\u0085\u00A0\u1680\u2000-\u200A\u2028\u2029\u202F\u205F\u3000]+$/g, "")
}

export function isSubjectKeywordTooLong(value: string): boolean {
  return Array.from(normalizeSubjectKeyword(value)).length > 255
}

interface SearchPage<T> { data: T[]; total: number; consumed?: number }
interface SearchOptions<T> {
  fetchPage: (keyword: string, page: number, signal: AbortSignal) => Promise<SearchPage<T>>
  enabled?: boolean
  emptyByDefault?: boolean
  delay?: number
  scopeKey?: string
}

/** Keeps query identity separate from display text and invalidates immediately on edit. */
export function useSubjectSearch<T>({ fetchPage, enabled = true, emptyByDefault = false, delay = 300, scopeKey = "" }: SearchOptions<T>) {
  const [keyword, setKeyword] = useState("")
  const [rows, setRows] = useState<T[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [failed, setFailed] = useState(false)
  const [revision, setRevision] = useState(0)
  const composing = useRef(false)
  const request = useRef<AbortController | null>(null)
  const fetchRef = useRef(fetchPage)
  fetchRef.current = fetchPage
  const current = useRef({ keyword: "", page: 1, loading: false, count: 0, total: 0 })
  const loadedScope = useRef(scopeKey)
  const scopeChanged = loadedScope.current !== scopeKey
  if (scopeChanged) request.current?.abort()
  const normalized = normalizeSubjectKeyword(keyword)
  const tooLong = isSubjectKeywordTooLong(keyword)

  const load = useCallback(async (query: string, page: number, append: boolean) => {
    if (composing.current) return
    request.current?.abort()
    const controller = new AbortController()
    request.current = controller
    current.current.loading = true
    setLoading(true)
    setFailed(false)
    try {
      const result = await fetchRef.current(query, page, controller.signal)
      if (controller.signal.aborted) return
      const consumed = result.consumed ?? result.data.length
      current.current = { keyword: query, page, loading: false, count: consumed === 0 ? result.total : append ? current.current.count + consumed : consumed, total: result.total }
      setRows(prev => append ? [...prev, ...result.data] : result.data)
      setTotal(result.total)
    } catch {
      if (!controller.signal.aborted) setFailed(true)
    } finally {
      if (!controller.signal.aborted) {
        current.current.loading = false
        setLoading(false)
      }
    }
  }, [])

  const changeKeyword = useCallback((value: string) => {
    request.current?.abort()
    current.current = { keyword: normalizeSubjectKeyword(value), page: 1, loading: true, count: 0, total: 0 }
    setRows([])
    setFailed(false)
    setKeyword(value)
    setRevision(v => v + 1)
    setLoading(!composing.current && !isSubjectKeywordTooLong(value) && (!emptyByDefault || !!normalizeSubjectKeyword(value)))
  }, [emptyByDefault])

  useEffect(() => {
    request.current?.abort()
    loadedScope.current = scopeKey
    current.current = { keyword: normalized, page: 1, loading: true, count: 0, total: 0 }
    setRows([])
    setTotal(0)
    setFailed(false)
    if (!enabled || composing.current || tooLong || (emptyByDefault && !normalized)) {
      setLoading(false)
      setRows([])
      return
    }
    setLoading(true)
    const timer = setTimeout(() => void load(normalized, 1, false), delay)
    return () => { clearTimeout(timer); request.current?.abort() }
  }, [enabled, normalized, revision, tooLong, emptyByDefault, delay, scopeKey, load])

  const loadMore = useCallback(() => {
    const state = current.current
    if (!enabled || failed || scopeChanged || composing.current || tooLong || state.loading || state.count >= state.total) return
    void load(state.keyword, state.page + 1, true)
  }, [enabled, failed, scopeChanged, tooLong, load])

  const retry = () => {
    if (!enabled || tooLong || composing.current) return
    const state = current.current
    const append = state.keyword === normalized && state.count > 0
    void load(normalized, append ? state.page + 1 : 1, append)
  }

  return {
    keyword, normalized, tooLong, rows: scopeChanged ? [] : rows, total: scopeChanged ? 0 : total, loading: enabled && scopeChanged || loading, failed: !scopeChanged && failed, changeKeyword, loadMore, retry,
    inputProps: {
      value: keyword,
      onChange: (event: ChangeEvent<HTMLInputElement>) => changeKeyword(event.target.value),
      onCompositionStart: () => { composing.current = true; request.current?.abort(); setRows([]); setLoading(false); setRevision(value => value + 1) },
      onCompositionEnd: (event: CompositionEvent<HTMLInputElement>) => { composing.current = false; changeKeyword(event.currentTarget.value) },
      onPaste: (event: ClipboardEvent<HTMLInputElement>) => {
        const pasted = event.clipboardData.getData("text")
        if (!/[\r\n]/.test(pasted)) return
        event.preventDefault()
        const input = event.currentTarget
        changeKeyword(input.value.slice(0, input.selectionStart ?? 0) + pasted.replace(/\r\n|[\r\n]/g, " ") + input.value.slice(input.selectionEnd ?? input.value.length))
      },
    },
  }
}
