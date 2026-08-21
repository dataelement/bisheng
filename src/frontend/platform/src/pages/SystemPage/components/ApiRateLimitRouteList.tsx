import { PlusIcon, SearchIcon } from "@/components/bs-icons"
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
import { Button } from "@/components/bs-ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/bs-ui/dialog"
import { Input } from "@/components/bs-ui/input"
import AutoPagination from "@/components/bs-ui/pagination/autoPagination"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/bs-ui/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/bs-ui/table"
import { toast } from "@/components/bs-ui/toast/use-toast"
import type {
  ApiRateLimitLimits,
  ApiRateLimitMatchType,
  ApiRateLimitMethod,
  ApiRateLimitRouteCatalogItem,
  ApiRateLimitRouteRule
} from "@/controllers/API/apiRateLimit"
import { useMemo, useState } from "react"
import { useTranslation } from "react-i18next"
import ApiRateLimitFields from "./ApiRateLimitFields"
import ApiRateLimitRoutePicker from "./ApiRateLimitRoutePicker"
import {
  EMPTY_LIMITS,
  MAX_API_RATE_LIMIT_ROUTES,
  findInvalidApiRateLimitRule,
  normalizeApiRateLimitRule
} from "./apiRateLimitValidation"

const DEFAULT_PAGE_SIZE = 10
const PAGE_SIZE_OPTIONS = [10, 20, 50]
const MATCH_TYPES: ApiRateLimitMatchType[] = ["METHOD_PATH", "PATH", "PREFIX"]
const METHODS: ApiRateLimitMethod[] = [
  "GET",
  "POST",
  "PUT",
  "PATCH",
  "DELETE",
  "OPTIONS",
  "HEAD"
]
const DIMENSIONS: Array<keyof ApiRateLimitLimits> = [
  "second",
  "minute",
  "hour",
  "day"
]

interface ApiRateLimitRouteListProps {
  routes: ApiRateLimitRouteRule[]
  onChange: (routes: ApiRateLimitRouteRule[]) => void
}

function newRule(): ApiRateLimitRouteRule {
  return {
    id: crypto.randomUUID(),
    match_type: "METHOD_PATH",
    method: "GET",
    path: "",
    limits: { ...EMPTY_LIMITS },
    message: ""
  }
}

export default function ApiRateLimitRouteList({
  routes,
  onChange
}: ApiRateLimitRouteListProps) {
  const { t } = useTranslation()
  const [queryInput, setQueryInput] = useState("")
  const [keyword, setKeyword] = useState("")
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [draft, setDraft] = useState<ApiRateLimitRouteRule>(() => newRule())

  const filteredRoutes = useMemo(() => {
    const normalizedKeyword = keyword.trim().toLowerCase()
    if (!normalizedKeyword) return routes
    return routes.filter((rule) =>
      [rule.match_type, rule.method || "", rule.path, rule.message].some(
        (value) => value.toLowerCase().includes(normalizedKeyword)
      )
    )
  }, [keyword, routes])

  const totalPages = Math.max(1, Math.ceil(filteredRoutes.length / pageSize))
  const safePage = Math.min(page, totalPages)
  const pageRows = filteredRoutes.slice(
    (safePage - 1) * pageSize,
    safePage * pageSize
  )

  const handleQuery = () => {
    setKeyword(queryInput)
    setPage(1)
  }

  const handleReset = () => {
    setQueryInput("")
    setKeyword("")
    setPage(1)
  }

  const handleCreate = () => {
    setEditingId(null)
    setDraft(newRule())
    setDialogOpen(true)
  }

  const handleEdit = (rule: ApiRateLimitRouteRule) => {
    setEditingId(rule.id)
    setDraft({ ...rule, limits: { ...rule.limits } })
    setDialogOpen(true)
  }

  const handleConfirm = () => {
    const normalizedDraft = normalizeApiRateLimitRule(draft)
    const nextRoutes = editingId
      ? routes.map((rule) => (rule.id === editingId ? normalizedDraft : rule))
      : [...routes, normalizedDraft]
    const invalidRule = findInvalidApiRateLimitRule(nextRoutes)
    if (invalidRule !== null) {
      toast({
        title: t("prompt"),
        variant: "error",
        description: t("system.apiRateLimit.ruleInvalid", {
          index: invalidRule + 1
        })
      })
      return
    }

    onChange(nextRoutes)
    setDialogOpen(false)
    if (!editingId) {
      setQueryInput("")
      setKeyword("")
      setPage(Math.max(1, Math.ceil(nextRoutes.length / pageSize)))
    }
  }

  const handleDelete = (rule: ApiRateLimitRouteRule) => {
    bsConfirm({
      desc: t("system.apiRateLimit.deleteConfirm", { path: rule.path }),
      onOk: (close) => {
        const nextRoutes = routes.filter((item) => item.id !== rule.id)
        onChange(nextRoutes)
        setPage(
          Math.min(
            safePage,
            Math.max(1, Math.ceil(nextRoutes.length / pageSize))
          )
        )
        close()
      }
    })
  }

  const formatLimits = (limits: ApiRateLimitLimits) => {
    const active = DIMENSIONS.flatMap((dimension) => {
      const value = limits[dimension]
      return value == null
        ? []
        : [`${t(`system.apiRateLimit.dimensions.${dimension}`)}: ${value}`]
    })
    return active.length > 0
      ? active.join(" / ")
      : t("system.apiRateLimit.unlimited")
  }

  return (
    <section className="space-y-3 rounded-md border p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-medium">
            {t("system.apiRateLimit.routesTitle")}
          </h2>
          <p className="text-xs text-muted-foreground">
            {t("system.apiRateLimit.routesHelp")}
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          disabled={routes.length >= MAX_API_RATE_LIMIT_ROUTES}
          onClick={handleCreate}
        >
          <PlusIcon className="mr-1 h-4 w-4" />
          {t("system.apiRateLimit.addRoute")}
        </Button>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Input
          className="max-w-md"
          value={queryInput}
          placeholder={t("system.apiRateLimit.searchPlaceholder")}
          onChange={(event) => setQueryInput(event.target.value)}
          onKeyDown={(event) => event.key === "Enter" && handleQuery()}
        />
        <Button type="button" onClick={handleQuery}>
          <SearchIcon className="mr-1 h-4 w-4" />
          {t("system.apiRateLimit.query")}
        </Button>
        <Button type="button" variant="outline" onClick={handleReset}>
          {t("system.apiRateLimit.reset")}
        </Button>
      </div>

      <div className="overflow-x-auto rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>
                {t("system.apiRateLimit.columns.matchType")}
              </TableHead>
              <TableHead>{t("system.apiRateLimit.columns.method")}</TableHead>
              <TableHead>{t("system.apiRateLimit.columns.path")}</TableHead>
              <TableHead>{t("system.apiRateLimit.columns.limits")}</TableHead>
              <TableHead>{t("system.apiRateLimit.columns.message")}</TableHead>
              <TableHead className="text-right">
                {t("system.apiRateLimit.columns.actions")}
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {pageRows.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={6}
                  className="text-center text-muted-foreground"
                >
                  {keyword
                    ? t("system.apiRateLimit.noSearchResults")
                    : t("system.apiRateLimit.emptyRoutes")}
                </TableCell>
              </TableRow>
            ) : (
              pageRows.map((rule) => (
                <TableRow key={rule.id}>
                  <TableCell>
                    {t(`system.apiRateLimit.matchTypes.${rule.match_type}`)}
                  </TableCell>
                  <TableCell>
                    {rule.method || t("system.apiRateLimit.anyMethod")}
                  </TableCell>
                  <TableCell className="max-w-96 break-all font-mono text-xs">
                    {rule.path}
                  </TableCell>
                  <TableCell className="min-w-64 text-xs">
                    {formatLimits(rule.limits)}
                  </TableCell>
                  <TableCell className="max-w-64 truncate text-xs text-muted-foreground">
                    {rule.message || t("system.apiRateLimit.useGlobalMessage")}
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-right">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => handleEdit(rule)}
                    >
                      {t("system.apiRateLimit.editRoute")}
                    </Button>
                    <Button
                      className="ml-2"
                      size="sm"
                      variant="destructive"
                      onClick={() => handleDelete(rule)}
                    >
                      {t("system.apiRateLimit.deleteRoute")}
                    </Button>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      <AutoPagination
        className="m-0 justify-end"
        page={safePage}
        pageSize={pageSize}
        total={filteredRoutes.length}
        showTotal
        pageSizeOptions={PAGE_SIZE_OPTIONS}
        onChange={setPage}
        onPageSizeChange={(size) => {
          setPageSize(size)
          setPage(1)
        }}
      />

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-h-[92vh] w-[calc(100vw-2rem)] max-w-4xl overflow-y-auto sm:min-h-[520px]">
          <DialogHeader>
            <DialogTitle>
              {t(
                editingId
                  ? "system.apiRateLimit.editRoute"
                  : "system.apiRateLimit.createRoute"
              )}
            </DialogTitle>
            <DialogDescription>
              {t("system.apiRateLimit.routesHelp")}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="grid gap-3 md:grid-cols-[180px_140px_minmax(0,1fr)]">
              <label className="space-y-1 text-sm">
                <span>{t("system.apiRateLimit.columns.matchType")}</span>
                <Select
                  value={draft.match_type}
                  onValueChange={(value) =>
                    setDraft({
                      ...draft,
                      match_type: value as ApiRateLimitMatchType,
                      method:
                        value === "METHOD_PATH" ? draft.method || "GET" : null
                    })
                  }
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {MATCH_TYPES.map((type) => (
                      <SelectItem key={type} value={type}>
                        {t(`system.apiRateLimit.matchTypes.${type}`)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </label>
              <label className="space-y-1 text-sm">
                <span>{t("system.apiRateLimit.columns.method")}</span>
                {draft.match_type === "METHOD_PATH" ? (
                  <Select
                    value={draft.method || "GET"}
                    onValueChange={(method) =>
                      setDraft({
                        ...draft,
                        method: method as ApiRateLimitMethod
                      })
                    }
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {METHODS.map((method) => (
                        <SelectItem key={method} value={method}>
                          {method}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <div className="flex h-8 items-center rounded-md border px-3 text-muted-foreground">
                    {t("system.apiRateLimit.anyMethod")}
                  </div>
                )}
              </label>
              <div className="space-y-1 text-sm">
                <span>{t("system.apiRateLimit.columns.path")}</span>
                <ApiRateLimitRoutePicker
                  ruleId={draft.id}
                  matchType={draft.match_type}
                  path={draft.path}
                  onPathChange={(path) => setDraft({ ...draft, path })}
                  onRouteSelect={(route: ApiRateLimitRouteCatalogItem) =>
                    setDraft({
                      ...draft,
                      path: route.path,
                      method:
                        draft.match_type === "METHOD_PATH" ? route.method : null
                    })
                  }
                />
              </div>
            </div>
            <ApiRateLimitFields
              value={draft.limits}
              onChange={(limits) => setDraft({ ...draft, limits })}
            />
            <label className="block space-y-1 text-sm">
              <span>{t("system.apiRateLimit.message")}</span>
              <Input
                value={draft.message}
                maxLength={500}
                placeholder={t("system.apiRateLimit.routeMessagePlaceholder")}
                onChange={(event) =>
                  setDraft({ ...draft, message: event.target.value })
                }
              />
            </label>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>
              {t("cancel")}
            </Button>
            <Button onClick={handleConfirm}>{t("confirmButton")}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  )
}
