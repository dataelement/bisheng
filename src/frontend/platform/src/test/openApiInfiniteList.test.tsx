import { act, cleanup, render, renderHook, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"
import { OpenApiListFooter } from "@/pages/SystemPage/components/OpenApiList/OpenApiListFooter"
import { useOpenApiList } from "@/pages/SystemPage/components/OpenApiList/useOpenApiList"

type Page = { data: { id: number; name?: string }[]; total: number }
const page = (ids: number[], total: number): Page => ({ data: ids.map((id) => ({ id })), total })
function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: Error) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe("Open API management infinite lists", () => {
  it("locks concurrent loads, appends without clearing rows, deduplicates and stops at total", async () => {
    const pending = deferred<Page>()
    const fetchPage = vi.fn<(page: number, size: number) => Promise<Page>>()
      .mockResolvedValueOnce(page([3, 2], 3))
      .mockReturnValueOnce(pending.promise)
    const { result } = renderHook(() => useOpenApiList(fetchPage))
    expect(result.current.initialLoading).toBe(true)
    expect(result.current.isEmpty).toBe(false)
    await waitFor(() => expect(result.current.status).toBe("idle"))
    act(() => { result.current.loadMore(); result.current.loadMore() })
    expect(fetchPage.mock.calls).toEqual([[1, 20], [2, 20]])
    expect(result.current.items.map((item) => item.id)).toEqual([3, 2])
    expect(result.current.initialLoading).toBe(false)
    await act(async () => pending.resolve(page([2, 1], 3)))
    expect(result.current.items.map((item) => item.id)).toEqual([3, 2, 1])
    expect(result.current.status).toBe("done")
    act(() => result.current.loadMore())
    expect(fetchPage).toHaveBeenCalledTimes(2)
  })

  it("retains rows after failure and retries the failed page only on request", async () => {
    const fetchPage = vi.fn<(page: number, size: number) => Promise<Page>>()
      .mockResolvedValueOnce(page([2], 2))
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(page([1], 2))
    const { result } = renderHook(() => useOpenApiList(fetchPage))
    await waitFor(() => expect(result.current.status).toBe("idle"))
    act(() => result.current.loadMore())
    await waitFor(() => expect(result.current.status).toBe("error"))
    expect(result.current.items).toEqual([{ id: 2 }])
    act(() => result.current.loadMore())
    expect(fetchPage).toHaveBeenCalledTimes(2)
    act(() => result.current.retry())
    await waitFor(() => expect(result.current.status).toBe("done"))
    expect(fetchPage.mock.calls).toEqual([[1, 20], [2, 20], [2, 20]])
  })

  it("distinguishes initial failure from an empty successful result", async () => {
    const fetchPage = vi.fn<(page: number, size: number) => Promise<Page>>()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(page([], 0))
    const { result } = renderHook(() => useOpenApiList(fetchPage))
    await waitFor(() => expect(result.current.status).toBe("error"))
    expect(result.current.isEmpty).toBe(false)
    act(() => result.current.retry())
    await waitFor(() => expect(result.current.isEmpty).toBe(true))
    expect(fetchPage.mock.calls).toEqual([[1, 20], [1, 20]])
  })

  it("ignores an old source response after the search or account changes", async () => {
    const stale = deferred<Page>()
    const fetchOld = vi.fn().mockReturnValue(stale.promise)
    const fetchNew = vi.fn().mockResolvedValue(page([99], 1))
    const { result, rerender } = renderHook(({ fetchPage }) => useOpenApiList<Page>(fetchPage), {
      initialProps: { fetchPage: fetchOld },
    })
    rerender({ fetchPage: fetchNew })
    await waitFor(() => expect(result.current.items).toEqual([{ id: 99 }]))
    await act(async () => stale.resolve(page([1], 100)))
    expect(result.current.items).toEqual([{ id: 99 }])
    expect(result.current.status).toBe("done")
  })

  it("ignores an in-flight append failure after refreshing following a mutation", async () => {
    const stale = deferred<Page>()
    const fetchPage = vi.fn<(page: number, size: number) => Promise<Page>>()
      .mockResolvedValueOnce(page([2], 2))
      .mockReturnValueOnce(stale.promise)
      .mockResolvedValueOnce(page([3, 2], 2))
    const { result } = renderHook(() => useOpenApiList(fetchPage))
    await waitFor(() => expect(result.current.status).toBe("idle"))
    act(() => result.current.loadMore())
    await act(async () => result.current.reload())
    await act(async () => stale.reject(new Error("old request failed")))
    expect(result.current.items.map((item) => item.id)).toEqual([3, 2])
    expect(result.current.status).toBe("done")
    expect(fetchPage.mock.calls).toEqual([[1, 20], [2, 20], [1, 20]])
  })

  it.each([{ ids: [] }, { ids: [2] }])("stops automatic loading when a page makes no progress: $ids", async ({ ids }) => {
    const fetchPage = vi.fn<(page: number, size: number) => Promise<Page>>()
      .mockResolvedValueOnce(page([2], 2))
      .mockResolvedValueOnce(page(ids, 2))
    const { result } = renderHook(() => useOpenApiList(fetchPage))
    await waitFor(() => expect(result.current.status).toBe("idle"))
    act(() => result.current.loadMore())
    await waitFor(() => expect(result.current.status).toBe("error"))
    act(() => result.current.loadMore())
    expect(fetchPage).toHaveBeenCalledTimes(2)
  })

  it("observes the scrolling parent, disconnects while loading and offers keyboard retry", async () => {
    const disconnect = vi.fn()
    let callback!: IntersectionObserverCallback
    let options: IntersectionObserverInit | undefined
    vi.stubGlobal("IntersectionObserver", class {
      constructor(cb: IntersectionObserverCallback, init?: IntersectionObserverInit) { callback = cb; options = init }
      observe = vi.fn()
      disconnect = disconnect
    })
    const onLoadMore = vi.fn()
    const onRetry = vi.fn()
    const view = (status: "idle" | "loading" | "error" | "done", itemCount = 1) => (
      <div data-testid="scroll-parent" style={{ overflowY: "auto" }}>
        <OpenApiListFooter status={status} itemCount={itemCount} onLoadMore={onLoadMore} onRetry={onRetry} />
      </div>
    )
    const { rerender } = render(view("idle"))
    expect(options?.root).toBe(screen.getByTestId("scroll-parent"))
    expect(options?.rootMargin).toBe("0px 0px 200px 0px")
    act(() => callback([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver))
    expect(onLoadMore).toHaveBeenCalledOnce()
    rerender(view("loading"))
    expect(disconnect).toHaveBeenCalledOnce()
    expect(screen.getByRole("status")).toHaveAttribute("aria-busy", "true")
    rerender(view("error"))
    screen.getByRole("button").focus()
    await userEvent.setup().keyboard("{Enter}")
    expect(onRetry).toHaveBeenCalledOnce()
    rerender(view("done"))
    expect(screen.getByText("openApiManagement.list.done")).toBeInTheDocument()
    rerender(view("done", 0))
    expect(screen.queryByText("openApiManagement.list.done")).not.toBeInTheDocument()
  })
})
