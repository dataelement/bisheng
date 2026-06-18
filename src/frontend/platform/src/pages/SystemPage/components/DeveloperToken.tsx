import { PlusIcon, SearchIcon } from "@/components/bs-icons"
import DepartmentUsersSelect, {
  DepartmentUserOption,
} from "@/components/bs-comp/selectComponent/DepartmentUsersSelect"
import { Badge } from "@/components/bs-ui/badge"
import { Button } from "@/components/bs-ui/button"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/bs-ui/dialog"
import { Input } from "@/components/bs-ui/input"
import { Switch } from "@/components/bs-ui/switch"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/bs-ui/table"
import { toast } from "@/components/bs-ui/toast/use-toast"
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
import {
  createDeveloperTokenApi,
  deleteDeveloperTokenApi,
  DeveloperTokenGlobalConfig,
  DeveloperTokenPayload,
  DeveloperTokenRecord,
  getDeveloperTokenDetailApi,
  getDeveloperTokenGlobalConfigApi,
  listDeveloperTokensApi,
  updateDeveloperTokenApi,
  updateDeveloperTokenGlobalConfigApi,
  viewDeveloperTokenSecretApi,
} from "@/controllers/API/developerToken"
import { userContext } from "@/contexts/userContext"
import { formatIsoDateTime } from "@/util/utils"
import type { ClipboardEvent, CompositionEvent, FormEvent, KeyboardEvent } from "react"
import { useContext, useEffect, useMemo, useState } from "react"
import { useTranslation } from "react-i18next"
import {
  findInvalidIpWhitelistRule,
  formatLimitInput,
  isRateLimitControlKey,
  isRateLimitInputAllowed,
  isRateLimitValueValid,
  parseLimit,
  sanitizeRateLimitInput,
} from "./developerTokenValidation"

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
}

const emptyConfig: DeveloperTokenGlobalConfig = {
  ip_whitelist: "",
  rate_limit_per_minute: null,
}

function toForm(row?: DeveloperTokenRecord): TokenFormState {
  return {
    id: row?.id,
    name: row?.name || "",
    user: row?.user_id
      ? [{ label: row.user_name || String(row.user_id), value: Number(row.user_id) }]
      : [],
    binding_changed: false,
    enabled: row?.enabled ?? true,
    override_ip_whitelist: row?.override_ip_whitelist ?? false,
    ip_whitelist: row?.ip_whitelist || "",
    override_rate_limit: row?.override_rate_limit ?? false,
    rate_limit_per_minute: row?.rate_limit_per_minute != null
      ? String(row.rate_limit_per_minute)
      : "",
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

function StatusBadge({ enabled }: { enabled: boolean }) {
  const { t } = useTranslation()
  return enabled ? (
    <Badge variant="default">{t("system.developerToken.enabled")}</Badge>
  ) : (
    <Badge variant="destructive">{t("system.developerToken.disabled")}</Badge>
  )
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
  const [config, setConfig] = useState<DeveloperTokenGlobalConfig>(emptyConfig)
  const [globalRateLimit, setGlobalRateLimit] = useState("")
  const [configSaving, setConfigSaving] = useState(false)
  const [formOpen, setFormOpen] = useState(false)
  const [form, setForm] = useState<TokenFormState>(() => toForm())
  const [saving, setSaving] = useState(false)
  const [secretOpen, setSecretOpen] = useState(false)
  const [secret, setSecret] = useState("")

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

  const loadConfig = async () => {
    if (!isSuperAdmin) return
    const result = await getDeveloperTokenGlobalConfigApi()
    setConfig(result)
    setGlobalRateLimit(formatLimitInput(result.rate_limit_per_minute))
  }

  useEffect(() => {
    loadList(1)
    loadConfig()
  }, [])

  const handleOpenCreate = () => {
    setForm(toForm())
    setFormOpen(true)
  }

  const handleOpenEdit = async (row: DeveloperTokenRecord) => {
    const detail = await getDeveloperTokenDetailApi(row.id)
    setForm(toForm(detail))
    setFormOpen(true)
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

  const handleSaveConfig = async () => {
    const invalidIpRule = findInvalidIpWhitelistRule(config.ip_whitelist)
    if (invalidIpRule) {
      showIpWhitelistError(invalidIpRule)
      return
    }
    if (!isRateLimitValueValid(globalRateLimit)) {
      showRateLimitError()
      return
    }
    setConfigSaving(true)
    try {
      const result = await updateDeveloperTokenGlobalConfigApi({
        ip_whitelist: config.ip_whitelist || "",
        rate_limit_per_minute: parseLimit(globalRateLimit),
      })
      setConfig(result)
      setGlobalRateLimit(formatLimitInput(result.rate_limit_per_minute))
      toast({
        title: t("prompt"),
        variant: "success",
        description: t("system.developerToken.saved"),
      })
    } finally {
      setConfigSaving(false)
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-4 overflow-auto p-4">
      {isSuperAdmin && (
        <div className="space-y-3 border-b pb-4">
          <div className="grid gap-3 md:grid-cols-[1fr_220px_auto]">
            <label className="space-y-1 text-sm">
              <span>{t("system.developerToken.globalWhitelist")}</span>
              <textarea
                className="min-h-20 w-full rounded-md border bg-search-input px-3 py-2 text-sm outline-none focus:ring-1 focus:ring-ring"
                value={config.ip_whitelist}
                onChange={(event) => setConfig({ ...config, ip_whitelist: event.target.value })}
                placeholder={t("system.developerToken.ipWhitelistPlaceholder")}
              />
              <div className="text-xs text-muted-foreground">
                {t("system.developerToken.ipWhitelistHelp")}
              </div>
            </label>
            <label className="space-y-1 text-sm">
              <span>{t("system.developerToken.globalRateLimit")}</span>
              <Input
                type="text"
                inputMode="numeric"
                pattern="[0-9]*"
                placeholder={t("system.developerToken.globalRateLimitPlaceholder")}
                value={globalRateLimit}
                onBeforeInput={handleRateLimitBeforeInput}
                onKeyDown={handleRateLimitKeyDown}
                onPaste={handleRateLimitPaste}
                onCompositionEnd={(event) => handleRateLimitCompositionEnd(event, setGlobalRateLimit)}
                onChange={(event) => handleRateLimitChange(event.target.value, setGlobalRateLimit)}
              />
            </label>
            <div className="flex items-end">
              <Button disabled={configSaving} onClick={handleSaveConfig}>
                {t("system.developerToken.saveConfig")}
              </Button>
            </div>
          </div>
        </div>
      )}

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

      <div className="min-h-0 rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("system.developerToken.columns.name")}</TableHead>
              <TableHead>{t("system.developerToken.columns.prefix")}</TableHead>
              <TableHead>{t("system.developerToken.columns.binding")}</TableHead>
              <TableHead>{t("system.developerToken.columns.status")}</TableHead>
              <TableHead>{t("system.developerToken.columns.controls")}</TableHead>
              <TableHead>{t("system.developerToken.columns.lastUsed")}</TableHead>
              <TableHead className="text-right">{t("system.developerToken.columns.actions")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && rows.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} className="text-center text-muted-foreground">
                  {t("system.developerToken.loading")}
                </TableCell>
              </TableRow>
            ) : rows.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} className="text-center text-muted-foreground">
                  {t("system.developerToken.empty")}
                </TableCell>
              </TableRow>
            ) : (
              rows.map((row) => (
                <TableRow key={row.id}>
                  <TableCell className="font-medium">{row.name}</TableCell>
                  <TableCell className="font-mono text-xs">{row.token_prefix}</TableCell>
                  <TableCell className="text-xs">
                    <div>{row.user_name || row.user_id}</div>
                    <div className="text-muted-foreground">{row.tenant_name || row.tenant_id}</div>
                  </TableCell>
                  <TableCell>
                    <StatusBadge enabled={row.enabled} />
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    <div>
                      {row.override_ip_whitelist
                        ? t("system.developerToken.overrideIp")
                        : t("system.developerToken.globalIp")}
                    </div>
                    <div>
                      {row.override_rate_limit
                        ? t("system.developerToken.overrideRate")
                        : t("system.developerToken.globalRate")}
                      {row.rate_limit_per_minute ? ` ${row.rate_limit_per_minute}/min` : ""}
                    </div>
                  </TableCell>
                  <TableCell className="text-xs">
                    <div>{row.last_used_time ? formatIsoDateTime(row.last_used_time) : "-"}</div>
                    <div className="text-muted-foreground">{row.last_used_ip || "-"}</div>
                  </TableCell>
                  <TableCell className="space-x-2 text-right">
                    <Button size="sm" variant="outline" onClick={() => handleOpenEdit(row)}>
                      {t("system.developerToken.edit")}
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => handleViewSecret(row)}>
                      {t("system.developerToken.viewSecret")}
                    </Button>
                    <Button size="sm" variant="destructive" onClick={() => handleDelete(row)}>
                      {t("system.developerToken.delete")}
                    </Button>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

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
        <DialogContent className="max-w-2xl">
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
                onChange={(value) => setForm({ ...form, user: value, binding_changed: true })}
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
