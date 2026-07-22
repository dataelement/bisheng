import { PlusIcon, SearchIcon } from "@/components/bs-icons"
import DepartmentUsersSelect, { DepartmentUserOption } from "@/components/bs-comp/selectComponent/DepartmentUsersSelect"
import { Button } from "@/components/bs-ui/button"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog"
import { Input } from "@/components/bs-ui/input"
import { Switch } from "@/components/bs-ui/switch"
import { toast } from "@/components/bs-ui/toast/use-toast"
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
import {
  createDeveloperTokenApi,
  deleteDeveloperTokenApi,
  DeveloperTokenDetail,
  DeveloperTokenFileSyncOptions,
  DeveloperTokenFileSyncRule,
  DeveloperTokenPayload,
  DeveloperTokenRecord,
  DeveloperTokenRouteRule,
  getDeveloperTokenDetailApi,
  getDeveloperTokenFileSyncOptionsApi,
  listDeveloperTokensApi,
  updateDeveloperTokenApi,
  viewDeveloperTokenSecretApi,
} from "@/controllers/API/developerToken"
import { userContext } from "@/contexts/userContext"
import type { ClipboardEvent, CompositionEvent, FormEvent, KeyboardEvent } from "react"
import { useContext, useEffect, useMemo, useRef, useState } from "react"
import { useTranslation } from "react-i18next"
import {
  findInvalidIpWhitelistRule,
  isRateLimitControlKey,
  isRateLimitInputAllowed,
  isRateLimitValueValid,
  parseLimit,
  sanitizeRateLimitInput,
} from "./developerTokenValidation"
import DeveloperTokenRouteAllowlist from "./DeveloperTokenRouteAllowlist"
import { findInvalidDeveloperTokenRouteRule, normalizeDeveloperTokenRouteWhitelist } from "./developerTokenRouteValidation"
import DeveloperTokenFileSyncRuleEditor from "./DeveloperTokenFileSyncRule"
import {
  findInvalidFileSyncRule,
  normalizeFileSyncRule,
} from "./developerTokenFileSyncRuleValidation"
import DeveloperTokenGlobalSettings from "./DeveloperTokenGlobalSettings"
import DeveloperTokenTable from "./DeveloperTokenTable"

const PAGE_SIZE = 20

interface TokenFormState {
  id?: number
  name: string
  user: DepartmentUserOption[]
  binding_changed: boolean
  enabled: boolean
  override_ip_whitelist: boolean
  ip_whitelist: string
  override_rate_limit: boolean
  rate_limit_per_minute: string
  route_whitelist: DeveloperTokenRouteRule[]
  tenant_id: number | null
  file_sync_rule: DeveloperTokenFileSyncRule | null
}

function toForm(row?: DeveloperTokenDetail): TokenFormState {
  return {
    id: row?.id,
    name: row?.name || "",
    user: row?.user_id ? [{
      label: row.user_name || String(row.user_id),
      value: Number(row.user_id),
      tenant_id: row.tenant_id,
    }] : [],
    binding_changed: false,
    enabled: row?.enabled ?? true,
    override_ip_whitelist: row?.override_ip_whitelist ?? false,
    ip_whitelist: row?.ip_whitelist || "",
    override_rate_limit: row?.override_rate_limit ?? false,
    rate_limit_per_minute: row?.rate_limit_per_minute != null ? String(row.rate_limit_per_minute) : "",
    route_whitelist: row?.route_whitelist || [],
    tenant_id: row?.tenant_id ?? null,
    file_sync_rule: row?.file_sync_rule ?? null,
  }
}

function asPayload(form: TokenFormState): DeveloperTokenPayload {
  const payload: DeveloperTokenPayload = {
    name: form.name.trim(),
    enabled: form.enabled,
    override_ip_whitelist: form.override_ip_whitelist,
    ip_whitelist: form.ip_whitelist,
    override_rate_limit: form.override_rate_limit,
    rate_limit_per_minute: parseLimit(form.rate_limit_per_minute),
    route_whitelist: normalizeDeveloperTokenRouteWhitelist(form.route_whitelist),
    file_sync_rule: normalizeFileSyncRule(form.file_sync_rule),
  }
  if (!form.id || form.binding_changed) {
    const selected = form.user[0]
    payload.user_id = selected?.value
    payload.department_id = selected?.department_id
    payload.dept_id = selected?.dept_id
  }
  return payload
}

function hasSelectedBindingContext(form: TokenFormState): boolean {
  const selected = form.user[0]
  return Boolean(selected && (selected.department_id != null || selected.dept_id))
}

export default function DeveloperToken() {
  const { t } = useTranslation()
  const { user } = useContext(userContext)
  const isSuperAdmin = user?.role === "admin"

  const [rows, setRows] = useState<DeveloperTokenRecord[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [keyword, setKeyword] = useState("")
  const [loading, setLoading] = useState(false)
  const [formOpen, setFormOpen] = useState(false)
  const [form, setForm] = useState<TokenFormState>(() => toForm())
  const [saving, setSaving] = useState(false)
  const [secretOpen, setSecretOpen] = useState(false)
  const [secret, setSecret] = useState("")
  const [fileSyncOptions, setFileSyncOptions] = useState<DeveloperTokenFileSyncOptions | null>(null)
  const [fileSyncOptionsLoading, setFileSyncOptionsLoading] = useState(false)
  const [fileSyncOptionsError, setFileSyncOptionsError] = useState<string | null>(null)
  const fileSyncTenantIdRef = useRef<number | null>(null)

  const maxPage = useMemo(() => Math.max(1, Math.ceil(total / PAGE_SIZE)), [total])

  const loadList = async (nextPage = page) => {
    setLoading(true)
    try {
      const result = await listDeveloperTokensApi({
        page: nextPage,
        limit: PAGE_SIZE,
        keyword: keyword.trim() || undefined,
      })
      setRows(result.data)
      setTotal(result.total)
      setPage(nextPage)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadList(1)
  }, [])

  useEffect(() => {
    const tenantId = form.tenant_id
    fileSyncTenantIdRef.current = tenantId
    if (!formOpen || !tenantId) {
      setFileSyncOptions(null)
      setFileSyncOptionsError(null)
      setFileSyncOptionsLoading(false)
      return
    }
    let active = true
    setFileSyncOptions(null)
    setFileSyncOptionsError(null)
    setFileSyncOptionsLoading(true)
    void getDeveloperTokenFileSyncOptionsApi({
      tenant_id: tenantId,
      space_page: 1,
      space_limit: 200,
    }).then((result) => {
      if (active && result.tenant_id === tenantId) setFileSyncOptions(result)
    }).catch(() => {
      if (active) setFileSyncOptionsError("load_failed")
    }).finally(() => {
      if (active) setFileSyncOptionsLoading(false)
    })
    return () => {
      active = false
    }
  }, [form.tenant_id, formOpen])

  const handleOpenCreate = () => {
    setForm(toForm())
    setFormOpen(true)
  }

  const handleOpenEdit = async (row: DeveloperTokenRecord) => {
    const detail = await getDeveloperTokenDetailApi(row.id)
    setForm(toForm(detail))
    setFormOpen(true)
  }

  const handleBindingChange = (value: DepartmentUserOption[]) => {
    const selectedTenantId = Number(value[0]?.tenant_id ?? user?.tenant_id) || null
    const tenantChanged = selectedTenantId !== form.tenant_id
    fileSyncTenantIdRef.current = selectedTenantId
    setForm({
      ...form,
      user: value,
      binding_changed: true,
      tenant_id: selectedTenantId,
      file_sync_rule: tenantChanged ? null : form.file_sync_rule,
    })
    if (tenantChanged) {
      setFileSyncOptions(null)
      setFileSyncOptionsError(null)
    }
  }

  const handleSearchFileSyncSpaces = async (spaceKeyword: string) => {
    if (!form.tenant_id) return
    setFileSyncOptionsLoading(true)
    setFileSyncOptionsError(null)
    try {
      const result = await getDeveloperTokenFileSyncOptionsApi({
        tenant_id: form.tenant_id,
        space_page: 1,
        space_limit: 200,
        space_keyword: spaceKeyword || undefined,
      })
      if (result.tenant_id === fileSyncTenantIdRef.current) {
        setFileSyncOptions((current) => {
          if (!current || !spaceKeyword) return result
          const spaces = new Map(current.knowledge_spaces.data.map((item) => [item.id, item]))
          result.knowledge_spaces.data.forEach((item) => spaces.set(item.id, item))
          return {
            ...result,
            knowledge_spaces: {
              data: Array.from(spaces.values()),
              total: Math.max(current.knowledge_spaces.total, result.knowledge_spaces.total),
            },
          }
        })
      }
    } catch {
      setFileSyncOptionsError("load_failed")
    } finally {
      setFileSyncOptionsLoading(false)
    }
  }

  const fileSyncSummaryLabels = {
    notConfigured: t("system.developerToken.fileSync.summary.notConfigured"),
    businessDomain: t("system.developerToken.fileSync.summary.businessDomain"),
    targetSpace: t("system.developerToken.fileSync.summary.targetSpace"),
    dynamicDepartment: t("system.developerToken.fileSync.summary.dynamicDepartment"),
    dynamicResponsiblePerson: t("system.developerToken.fileSync.summary.dynamicResponsiblePerson"),
  }

  const showRateLimitError = () => {
    toast({
      title: t("prompt"),
      variant: "error",
      description: t("system.developerToken.rateLimitIntegerError"),
    })
  }

  const showIpWhitelistError = (rule: string) => {
    toast({
      title: t("prompt"),
      variant: "error",
      description: t("system.developerToken.ipWhitelistInvalidError", { rule }),
    })
  }

  const handleRateLimitChange = (value: string, onAccepted: (nextValue: string) => void) => {
    if (!isRateLimitInputAllowed(value)) {
      onAccepted(sanitizeRateLimitInput(value))
      showRateLimitError()
      return
    }
    onAccepted(value)
  }

  const handleRateLimitKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (isRateLimitControlKey(event.key) || event.metaKey || event.ctrlKey || event.altKey) {
      return
    }
    if (!/^\d$/.test(event.key)) {
      event.preventDefault()
    }
  }

  const handleRateLimitBeforeInput = (event: FormEvent<HTMLInputElement>) => {
    const nativeEvent = event.nativeEvent as InputEvent
    if (nativeEvent.data && !isRateLimitInputAllowed(nativeEvent.data)) {
      event.preventDefault()
    }
  }

  const handleRateLimitPaste = (event: ClipboardEvent<HTMLInputElement>) => {
    const value = event.clipboardData.getData("text")
    if (!isRateLimitInputAllowed(value)) {
      event.preventDefault()
      showRateLimitError()
    }
  }

  const handleRateLimitCompositionEnd = (
    event: CompositionEvent<HTMLInputElement>,
    onAccepted: (nextValue: string) => void
  ) => {
    const value = event.currentTarget.value
    if (isRateLimitInputAllowed(value)) return
    const sanitized = sanitizeRateLimitInput(value)
    event.currentTarget.value = sanitized
    onAccepted(sanitized)
    showRateLimitError()
  }

  const handleSave = async () => {
    const needsBindingContext = !form.id || form.binding_changed
    if (!form.name.trim() || form.user.length === 0 || (needsBindingContext && !hasSelectedBindingContext(form))) {
      toast({
        title: t("prompt"),
        variant: "error",
        description: t("system.developerToken.requiredError"),
      })
      return
    }
    if (!isRateLimitValueValid(form.rate_limit_per_minute)) {
      showRateLimitError()
      return
    }
    const invalidIpRule = findInvalidIpWhitelistRule(form.ip_whitelist)
    if (invalidIpRule) {
      showIpWhitelistError(invalidIpRule)
      return
    }
    const invalidRouteRule = findInvalidDeveloperTokenRouteRule(form.route_whitelist)
    if (invalidRouteRule) {
      toast({
        title: t("prompt"),
        variant: "error",
        description: t("system.developerToken.routeRules.invalidError", { index: invalidRouteRule.index + 1 }),
      })
      return
    }
    if (form.file_sync_rule) {
      if (fileSyncOptionsLoading || fileSyncOptionsError || !fileSyncOptions) {
        toast({
          title: t("prompt"),
          variant: "error",
          description: t("system.developerToken.fileSync.optionsRequiredError"),
        })
        return
      }
      const invalidFileSyncRule = findInvalidFileSyncRule(form.file_sync_rule, fileSyncOptions)
      if (invalidFileSyncRule) {
        toast({
          title: t("prompt"),
          variant: "error",
          description: t("system.developerToken.fileSync.invalidError", {
            field: t(`system.developerToken.fileSync.errorFields.${invalidFileSyncRule.field}`),
          }),
        })
        return
      }
    }
    setSaving(true)
    try {
      if (form.id) {
        await updateDeveloperTokenApi(form.id, asPayload(form))
      } else {
        const result = await createDeveloperTokenApi(asPayload(form))
        setSecret(result.plaintext_token)
        setSecretOpen(true)
      }
      setFormOpen(false)
      await loadList(1)
      toast({
        title: t("prompt"),
        variant: "success",
        description: t("system.developerToken.saved"),
      })
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = (row: DeveloperTokenRecord) => {
    bsConfirm({
      desc: t("system.developerToken.deleteConfirm", { name: row.name }),
      onOk: async (close) => {
        await deleteDeveloperTokenApi(row.id)
        close()
        await loadList(page)
      },
    })
  }

  const handleViewSecret = async (row: DeveloperTokenRecord) => {
    const result = await viewDeveloperTokenSecretApi(row.id)
    setSecret(result.plaintext_token)
    setSecretOpen(true)
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-4 overflow-auto p-4">
      {isSuperAdmin && <DeveloperTokenGlobalSettings />}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-72 items-center gap-2">
          <div className="relative w-72">
            <SearchIcon className="absolute left-2 top-2 h-4 w-4 text-muted-foreground" />
            <Input
              className="pl-8"
              placeholder={t("system.developerToken.searchPlaceholder")}
              value={keyword}
              onChange={(event) => setKeyword(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") loadList(1)
              }}
            />
          </div>
          <Button variant="outline" onClick={() => loadList(1)}>
            {t("system.developerToken.search")}
          </Button>
        </div>
        <Button onClick={handleOpenCreate}>
          <PlusIcon className="mr-1 h-4 w-4 text-primary" />
          {t("system.developerToken.create")}
        </Button>
      </div>

      <DeveloperTokenTable
        rows={rows}
        loading={loading}
        fileSyncSummaryLabels={fileSyncSummaryLabels}
        onEdit={handleOpenEdit}
        onViewSecret={handleViewSecret}
        onDelete={handleDelete}
      />

      {total > 0 && (
        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <span>{t("system.developerToken.total", { total, page, maxPage })}</span>
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="outline"
              disabled={page <= 1 || loading}
              onClick={() => loadList(page - 1)}
            >
              {t("system.developerToken.prev")}
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={page >= maxPage || loading}
              onClick={() => loadList(page + 1)}
            >
              {t("system.developerToken.next")}
            </Button>
          </div>
        </div>
      )}

      <Dialog open={formOpen} onOpenChange={setFormOpen}>
        <DialogContent className="max-h-[90vh] max-w-3xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>
              {form.id ? t("system.developerToken.edit") : t("system.developerToken.create")}
            </DialogTitle>
          </DialogHeader>
          <div className="grid gap-3 md:grid-cols-2">
            <label className="space-y-1 text-sm">
              <span>{t("system.developerToken.fields.name")}</span>
              <Input value={form.name} placeholder={t("system.developerToken.namePlaceholder")} onChange={(event) => setForm({ ...form, name: event.target.value })} />
            </label>
            <div className="space-y-1 text-sm">
              <span>{t("system.developerToken.fields.user")}</span>
              <DepartmentUsersSelect
                multiple={false}
                value={form.user}
                onChange={handleBindingChange}
                placeholder={t("system.developerToken.selectUser")}
                searchPlaceholder={t("system.developerToken.searchUser")}
              />
              {form.user[0]?.department_path && (
                <div className="text-xs text-muted-foreground">{form.user[0].department_path}</div>
              )}
            </div>
            <label className="flex items-center justify-between rounded-md border px-3 py-2 text-sm">
              <span>{t("system.developerToken.fields.enabled")}</span>
              <Switch checked={form.enabled} onCheckedChange={(value) => setForm({ ...form, enabled: value })} />
            </label>
            <label className="flex items-center justify-between rounded-md border px-3 py-2 text-sm">
              <span>{t("system.developerToken.fields.overrideIp")}</span>
              <Switch
                checked={form.override_ip_whitelist}
                onCheckedChange={(value) => setForm({ ...form, override_ip_whitelist: value })}
              />
            </label>
            <label className="flex items-center justify-between rounded-md border px-3 py-2 text-sm">
              <span>{t("system.developerToken.fields.overrideRate")}</span>
              <Switch
                checked={form.override_rate_limit}
                onCheckedChange={(value) => setForm({ ...form, override_rate_limit: value })}
              />
            </label>
            <label className="space-y-1 text-sm md:col-span-2">
              <span>{t("system.developerToken.fields.ipWhitelist")}</span>
              <textarea
                className="min-h-24 w-full rounded-md border bg-search-input px-3 py-2 text-sm outline-none focus:ring-1 focus:ring-ring"
                value={form.ip_whitelist}
                onChange={(event) => setForm({ ...form, ip_whitelist: event.target.value })}
                placeholder={t("system.developerToken.ipWhitelistPlaceholder")}
              />
              <div className="text-xs text-muted-foreground">
                {t("system.developerToken.ipWhitelistHelp")}
              </div>
            </label>
            <label className="space-y-1 text-sm">
              <span>{t("system.developerToken.fields.rateLimit")}</span>
              <Input
                type="text"
                inputMode="numeric"
                pattern="[0-9]*"
                placeholder={t("system.developerToken.rateLimitPlaceholder")}
                value={form.rate_limit_per_minute}
                onBeforeInput={handleRateLimitBeforeInput}
                onKeyDown={handleRateLimitKeyDown}
                onPaste={handleRateLimitPaste}
                onCompositionEnd={(event) => handleRateLimitCompositionEnd(
                  event,
                  (value) => setForm({ ...form, rate_limit_per_minute: value })
                )}
                onChange={(event) => handleRateLimitChange(
                  event.target.value,
                  (value) => setForm({ ...form, rate_limit_per_minute: value })
                )}
              />
            </label>
            <DeveloperTokenRouteAllowlist
              value={form.route_whitelist}
              onChange={(route_whitelist) => setForm({ ...form, route_whitelist })}
            />
            <DeveloperTokenFileSyncRuleEditor
              value={form.file_sync_rule}
              onChange={(file_sync_rule) => setForm({ ...form, file_sync_rule })}
              options={fileSyncOptions}
              loading={fileSyncOptionsLoading}
              error={fileSyncOptionsError}
              onSearchSpaces={handleSearchFileSyncSpaces}
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setFormOpen(false)}>
              {t("cancel")}
            </Button>
            <Button disabled={saving} onClick={handleSave}>
              {t("confirmButton")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={secretOpen} onOpenChange={setSecretOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("system.developerToken.secretTitle")}</DialogTitle>
          </DialogHeader>
          <div className="rounded-md border bg-muted/40 p-3 font-mono text-sm break-all">
            {secret}
          </div>
          <DialogFooter>
            <Button onClick={() => setSecretOpen(false)}>{t("confirmButton")}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
