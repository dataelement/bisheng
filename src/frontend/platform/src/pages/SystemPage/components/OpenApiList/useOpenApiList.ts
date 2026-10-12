import { useCallback, useEffect, useRef, useState } from "react"

type ListPage = { data: { id: number }[]; total: number }
export type ListStatus = "idle" | "loading" | "error" | "done"
type ListState<P extends ListPage> = {
  items: P["data"][number][]
  response: P | null
  page: number
  status: ListStatus
}

const PAGE_SIZE = 20

function emptyState<P extends ListPage>(): ListState<P> {
  return { items: [], response: null, page: 0, status: "loading" }
}

export function useOpenApiList<P extends ListPage>(
  fetchPage: (page: number, pageSize: number) => Promise<P>,
) {
  const [state, setState] = useState<ListState<P>>(emptyState)
  const current = useRef(state)
  const generation = useRef(0)
  const inFlight = useRef(false)

  const load = useCallback(async (page: number, reset = false) => {
    if (inFlight.current && !reset) return
    const requestGeneration = reset ? ++generation.current : generation.current
    inFlight.current = true
    const previous = reset ? emptyState<P>() : current.current
    const publish = (next: ListState<P>) => {
      current.current = next
      setState(next)
    }
    publish({ ...previous, status: "loading" })
    try {
      const response = await fetchPage(page, PAGE_SIZE)
      if (requestGeneration !== generation.current) return
      const merged = new Map(previous.items.map((item) => [item.id, item]))
      for (const item of response.data) merged.set(item.id, item)
      const items = [...merged.values()]
      // A non-advancing page must require retry, not repeatedly fire the observer.
      if (items.length === previous.items.length && items.length < response.total) {
        throw new Error("Pagination returned no new items before reaching total")
      }
      publish({
        items,
        response,
        page,
        status: items.length >= response.total ? "done" : "idle",
      })
    } catch {
      if (requestGeneration !== generation.current) return
      // The inline error state retains existing rows and retries the same page.
      publish({ ...previous, status: "error" })
    } finally {
      if (requestGeneration === generation.current) inFlight.current = false
    }
  }, [fetchPage])

  const reload = useCallback(() => load(1, true), [load])
  const invalidate = useCallback(() => {
    generation.current++
    inFlight.current = false
  }, [])
  useEffect(() => {
    void reload()
    return invalidate
  }, [reload, invalidate])

  const loadMore = useCallback(() => {
    if (current.current.status === "idle") void load(current.current.page + 1)
  }, [load])
  const retry = useCallback(() => {
    if (current.current.status === "error") void load(current.current.page + 1)
  }, [load])

  return {
    ...state,
    initialLoading: state.status === "loading" && state.page === 0,
    isEmpty: state.status === "done" && state.items.length === 0,
    reload,
    loadMore,
    retry,
  }
}
