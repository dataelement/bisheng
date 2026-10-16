import { useEffect, useRef, useState } from "react"
import { useSubjectSearch } from "./useSubjectSearch"

interface SubjectTableParams { page: number; pageSize: number; keyword: string; [key: string]: unknown }

/** Retains table pagination and caller filters while sharing the picker input rules. */
export function useSubjectTable<T>({ pageSize }: { pageSize: number }, fetchPage: (params: SubjectTableParams, signal: AbortSignal) => Promise<{ data: T[]; total: number }>) {
  const [page, updatePage] = useState(1)
  const [filters, setFilters] = useState<Record<string, unknown>>({})
  const [revision, setRevision] = useState(0)
  const previousKeyword = useRef("")
  const search = useSubjectSearch<T>({
    delay: 600,
    scopeKey: JSON.stringify([page, filters, revision]),
    fetchPage: (keyword, _page, signal) => fetchPage({ page, pageSize, keyword, ...filters }, signal),
  })
  useEffect(() => {
    if (previousKeyword.current !== search.normalized) { previousKeyword.current = search.normalized; updatePage(1) }
  }, [search.normalized])
  return {
    page, pageSize, data: search.loading || search.failed || search.tooLong ? [] : search.rows, total: search.total, loading: search.loading,
    setPage: updatePage, search: (keyword: string) => { updatePage(1); search.changeKeyword(keyword) },
    reload: () => setRevision(value => value + 1),
    filterData: (next: Record<string, unknown>) => { updatePage(1); setFilters(previous => ({ ...previous, ...next })) },
    subjectSearch: { ...search, retry: () => setRevision(value => value + 1) },
  }
}
