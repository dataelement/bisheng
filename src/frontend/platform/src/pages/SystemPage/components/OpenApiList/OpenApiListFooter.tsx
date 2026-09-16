import { Loader2 } from "lucide-react"
import { useEffect, useRef } from "react"
import { useTranslation } from "react-i18next"
import type { ListStatus } from "./useOpenApiList"

interface OpenApiListFooterProps {
  status: ListStatus
  itemCount: number
  onLoadMore: () => void
  onRetry: () => void
}

// Follow the knowledge-square sentinel: observe the nearest scrolling container.
function findScrollRoot(element: HTMLElement): HTMLElement | null {
  let parent = element.parentElement
  while (parent && parent !== document.body && parent !== document.documentElement) {
    if (["auto", "scroll", "overlay"].includes(getComputedStyle(parent).overflowY)) return parent
    parent = parent.parentElement
  }
  return null
}

export function OpenApiListFooter({ status, itemCount, onLoadMore, onRetry }: OpenApiListFooterProps) {
  const { t } = useTranslation()
  const sentinel = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const element = sentinel.current
    if (!element || status !== "idle") return
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) onLoadMore()
    }, { root: findScrollRoot(element), rootMargin: "0px 0px 200px 0px", threshold: 0 })
    observer.observe(element)
    return () => observer.disconnect()
  }, [status, itemCount, onLoadMore])

  return (
    <div ref={sentinel} role="status" aria-live="polite" aria-busy={status === "loading"}
      className={`flex h-10 w-full items-center justify-center gap-2 text-muted-foreground ${status === "done" ? "text-xs" : "text-sm"}`}>
      {status === "loading" ? <>
        <Loader2 aria-hidden="true" className="size-4 animate-spin motion-reduce:animate-pulse" />
        {t("openApiManagement.list.loading")}
      </> : null}
      {status === "error" ? (
        <button type="button" className="h-full w-full hover:text-foreground" onClick={onRetry}>
          {t("openApiManagement.list.retry")}
        </button>
      ) : null}
      {status === "done" && itemCount > 0 ? t("openApiManagement.list.done") : null}
    </div>
  )
}
