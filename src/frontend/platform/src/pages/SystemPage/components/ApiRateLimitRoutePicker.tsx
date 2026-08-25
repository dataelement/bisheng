import { DropDownIcon, LoadIcon, SearchIcon } from "@/components/bs-icons"
import { Button } from "@/components/bs-ui/button"
import { Input } from "@/components/bs-ui/input"
import {
  Popover,
  PopoverContent,
  PopoverTrigger
} from "@/components/bs-ui/popover"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/bs-ui/select"
import {
  getApiRateLimitRoutesApi,
  type ApiRateLimitMatchType,
  type ApiRateLimitMethod,
  type ApiRateLimitRouteCatalogItem
} from "@/controllers/API/apiRateLimit"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useTranslation } from "react-i18next"

const PAGE_SIZE = 50
const ALL_FILTER = "__all__"
const UNCATEGORIZED_TAG = "__uncategorized__"
const CATALOG_METHODS: ApiRateLimitMethod[] = [
  "GET",
  "POST",
  "PUT",
  "PATCH",
  "DELETE"
]

interface ApiRateLimitRoutePickerProps {
  ruleId: string
  matchType: ApiRateLimitMatchType
  path: string
  onPathChange: (path: string) => void
  onRouteSelect: (route: ApiRateLimitRouteCatalogItem) => void
}

function appendUniqueRoutes(
  current: ApiRateLimitRouteCatalogItem[],
  incoming: ApiRateLimitRouteCatalogItem[]
): ApiRateLimitRouteCatalogItem[] {
  const items = new Map(
    current.map((item) => [`${item.method}:${item.path}`, item] as const)
  )
  incoming.forEach((item) => items.set(`${item.method}:${item.path}`, item))
  return Array.from(items.values())
}

export default function ApiRateLimitRoutePicker({
  ruleId,
  matchType,
  path,
  onPathChange,
  onRouteSelect
}: ApiRateLimitRoutePickerProps) {
  const { t } = useTranslation()
  const portalContainerRef = useRef<HTMLDivElement>(null)
  const requestIdRef = useRef(0)
  const [mode, setMode] = useState<"catalog" | "manual">("catalog")
  const [open, setOpen] = useState(false)
  const [searchInput, setSearchInput] = useState("")
  const [keyword, setKeyword] = useState("")
  const [tag, setTag] = useState(ALL_FILTER)
  const [method, setMethod] = useState(ALL_FILTER)
  const [items, setItems] = useState<ApiRateLimitRouteCatalogItem[]>([])
  const [categories, setCategories] = useState<string[]>([])
  const [page, setPage] = useState(0)
  const [totalPages, setTotalPages] = useState(0)
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [loadFailed, setLoadFailed] = useState(false)

  const formatCategory = useCallback(
    (value: string) =>
      value === UNCATEGORIZED_TAG
        ? t("system.apiRateLimit.routeCatalog.uncategorized")
        : value,
    [t]
  )

  const loadRoutes = useCallback(
    async ({
      nextPage,
      replace,
      nextKeyword = keyword,
      nextTag = tag,
      nextMethod = method
    }: {
      nextPage: number
      replace: boolean
      nextKeyword?: string
      nextTag?: string
      nextMethod?: string
    }) => {
      const requestId = ++requestIdRef.current
      setLoading(true)
      setLoadFailed(false)
      try {
        const result = await getApiRateLimitRoutesApi({
          keyword: nextKeyword.trim() || undefined,
          tag: nextTag === ALL_FILTER ? undefined : nextTag,
          method:
            nextMethod === ALL_FILTER
              ? undefined
              : (nextMethod as ApiRateLimitMethod),
          page: nextPage,
          page_size: PAGE_SIZE
        })
        if (requestId !== requestIdRef.current) return
        setItems((current) =>
          replace ? result.items : appendUniqueRoutes(current, result.items)
        )
        setCategories(result.categories)
        setPage(result.page)
        setTotalPages(result.total_pages)
        setTotal(result.total)
      } catch {
        if (requestId === requestIdRef.current) setLoadFailed(true)
      } finally {
        if (requestId === requestIdRef.current) setLoading(false)
      }
    },
    [keyword, method, tag]
  )

  useEffect(() => {
    setMode("catalog")
    setOpen(false)
    setSearchInput("")
    setKeyword("")
    setTag(ALL_FILTER)
    setMethod(ALL_FILTER)
    setItems([])
    setCategories([])
    setPage(0)
    setTotalPages(0)
    setTotal(0)
    setLoadFailed(false)
  }, [ruleId])

  useEffect(
    () => () => {
      requestIdRef.current += 1
    },
    []
  )

  const groupedItems = useMemo(() => {
    const groups = new Map<string, ApiRateLimitRouteCatalogItem[]>()
    items.forEach((item) => {
      const group = groups.get(item.primary_tag) || []
      group.push(item)
      groups.set(item.primary_tag, group)
    })
    return Array.from(groups.entries())
  }, [items])

  const handleOpenChange = (nextOpen: boolean) => {
    setOpen(nextOpen)
    if (nextOpen && page === 0 && !loading) {
      void loadRoutes({ nextPage: 1, replace: true })
    }
  }

  const handleQuery = () => {
    setKeyword(searchInput)
    void loadRoutes({ nextPage: 1, replace: true, nextKeyword: searchInput })
  }

  const handleTagChange = (value: string) => {
    setTag(value)
    void loadRoutes({ nextPage: 1, replace: true, nextTag: value })
  }

  const handleMethodChange = (value: string) => {
    setMethod(value)
    void loadRoutes({ nextPage: 1, replace: true, nextMethod: value })
  }

  const handleSelect = (route: ApiRateLimitRouteCatalogItem) => {
    onRouteSelect(route)
    setOpen(false)
    if (matchType === "PREFIX") setMode("manual")
  }

  if (mode === "manual") {
    return (
      <div className="space-y-2">
        <Input
          value={path}
          placeholder={t("system.apiRateLimit.pathPlaceholder")}
          onChange={(event) => onPathChange(event.target.value)}
        />
        <Button
          type="button"
          size="sm"
          variant="link"
          onClick={() => setMode("catalog")}
        >
          {t("system.apiRateLimit.routeCatalog.useCatalog")}
        </Button>
      </div>
    )
  }

  return (
    <div ref={portalContainerRef} className="space-y-2">
      <Popover open={open} onOpenChange={handleOpenChange}>
        <PopoverTrigger asChild>
          <Button
            type="button"
            variant="outline"
            role="combobox"
            aria-label={t("system.apiRateLimit.routeCatalog.selectRoute")}
            aria-expanded={open}
            className="w-full justify-between overflow-hidden px-3 font-normal"
          >
            <span
              className={
                path
                  ? "truncate font-mono text-xs"
                  : "truncate text-muted-foreground"
              }
            >
              {path || t("system.apiRateLimit.routeCatalog.selectPlaceholder")}
            </span>
            <DropDownIcon className="ml-2 h-4 w-4 shrink-0 opacity-50" />
          </Button>
        </PopoverTrigger>
        <PopoverContent
          align="end"
          className="w-[min(680px,calc(100vw-3rem))] p-0"
          portalContainer={portalContainerRef.current}
        >
          <div className="space-y-3 border-b p-3">
            <div className="flex gap-2">
              <Input
                value={searchInput}
                placeholder={t(
                  "system.apiRateLimit.routeCatalog.searchPlaceholder"
                )}
                onChange={(event) => setSearchInput(event.target.value)}
                onKeyDown={(event) => event.key === "Enter" && handleQuery()}
              />
              <Button
                type="button"
                size="sm"
                onClick={handleQuery}
                disabled={loading}
              >
                <SearchIcon className="mr-1 h-4 w-4" />
                {t("system.apiRateLimit.query")}
              </Button>
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              <Select value={tag} onValueChange={handleTagChange}>
                <SelectTrigger
                  aria-label={t(
                    "system.apiRateLimit.routeCatalog.categoryFilter"
                  )}
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL_FILTER}>
                    {t("system.apiRateLimit.routeCatalog.allCategories")}
                  </SelectItem>
                  {categories.map((category) => (
                    <SelectItem key={category} value={category}>
                      {formatCategory(category)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select value={method} onValueChange={handleMethodChange}>
                <SelectTrigger
                  aria-label={t(
                    "system.apiRateLimit.routeCatalog.methodFilter"
                  )}
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL_FILTER}>
                    {t("system.apiRateLimit.routeCatalog.allMethods")}
                  </SelectItem>
                  {CATALOG_METHODS.map((value) => (
                    <SelectItem key={value} value={value}>
                      {value}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="max-h-[360px] overflow-y-auto p-2">
            {loading && items.length === 0 ? (
              <div className="flex items-center justify-center gap-2 py-10 text-sm text-muted-foreground">
                <LoadIcon className="h-4 w-4 animate-spin" />
                {t("system.apiRateLimit.routeCatalog.loading")}
              </div>
            ) : loadFailed ? (
              <div className="space-y-3 py-8 text-center text-sm text-muted-foreground">
                <p>{t("system.apiRateLimit.routeCatalog.loadFailed")}</p>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => setMode("manual")}
                >
                  {t("system.apiRateLimit.routeCatalog.manualInput")}
                </Button>
              </div>
            ) : groupedItems.length === 0 ? (
              <div className="py-10 text-center text-sm text-muted-foreground">
                {t("system.apiRateLimit.routeCatalog.empty")}
              </div>
            ) : (
              groupedItems.map(([category, routes]) => (
                <section key={category} className="mb-3 last:mb-0">
                  <h3 className="sticky top-0 bg-popover px-2 py-1 text-xs font-medium text-muted-foreground">
                    {formatCategory(category)}
                  </h3>
                  <div className="space-y-1">
                    {routes.map((route) => (
                      <button
                        key={`${route.method}:${route.path}`}
                        type="button"
                        className="flex w-full items-start gap-3 rounded-md px-2 py-2 text-left hover:bg-accent"
                        onClick={() => handleSelect(route)}
                      >
                        <span className="mt-0.5 min-w-14 rounded bg-muted px-1.5 py-0.5 text-center font-mono text-[11px]">
                          {route.method}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block break-all font-mono text-xs">
                            {route.path}
                          </span>
                          {(route.summary || route.name) && (
                            <span className="mt-1 block truncate text-xs text-muted-foreground">
                              {route.summary || route.name}
                            </span>
                          )}
                        </span>
                      </button>
                    ))}
                  </div>
                </section>
              ))
            )}
          </div>

          <div className="flex items-center justify-between gap-3 border-t p-3 text-xs text-muted-foreground">
            <span>
              {t("system.apiRateLimit.routeCatalog.total", { total })}
            </span>
            {page < totalPages && (
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={loading}
                onClick={() =>
                  void loadRoutes({ nextPage: page + 1, replace: false })
                }
              >
                {loading && <LoadIcon className="mr-1 h-4 w-4 animate-spin" />}
                {t("system.apiRateLimit.routeCatalog.loadMore")}
              </Button>
            )}
          </div>
        </PopoverContent>
      </Popover>
      {!open && (
        <Button
          type="button"
          size="sm"
          variant="link"
          onClick={() => setMode("manual")}
        >
          {t("system.apiRateLimit.routeCatalog.manualInput")}
        </Button>
      )}
    </div>
  )
}
