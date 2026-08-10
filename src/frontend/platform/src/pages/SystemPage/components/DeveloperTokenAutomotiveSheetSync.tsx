import { Button } from "@/components/bs-ui/button"
import { Badge } from "@/components/bs-ui/badge"
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/bs-ui/accordion"
import { Input } from "@/components/bs-ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/bs-ui/select"
import AutoPagination from "@/components/bs-ui/pagination/autoPagination"
import { Switch } from "@/components/bs-ui/switch"
import { toast } from "@/components/bs-ui/toast/use-toast"
import {
  AutomotiveSheetIntroSyncConfig,
  AutomotiveSheetIntroSyncRun,
  DeveloperTokenRecord,
  getAutomotiveSheetIntroSyncConfigApi,
  listAutomotiveSheetIntroSyncRunsApi,
  listDeveloperTokensApi,
  testAutomotiveSheetIntroSyncApi,
  updateAutomotiveSheetIntroSyncConfigApi,
} from "@/controllers/API/developerToken"
import { formatIsoDateTime } from "@/util/utils"
import type { ReactNode } from "react"
import { useCallback, useEffect, useMemo, useState } from "react"
import { useTranslation } from "react-i18next"
import {
  defaultAutomotiveSheetIntroSyncConfig,
  findInvalidAutomotiveSheetIntroSyncConfig,
  normalizeAutomotiveSheetIntroSyncConfig,
} from "./automotiveSheetIntroSyncValidation"
import {
  formatFileSyncRuleSummary,
  type FileSyncRuleSummaryLabels,
} from "./developerTokenFileSyncRuleValidation"

const UNSET_VALUE = "__unset__"
const RUNS_PAGE_SIZE = 5

function getRunStatusBadgeVariant(status: AutomotiveSheetIntroSyncRun["status"]) {
  if (status === "success") return "default"
  if (status === "running") return "secondary"
  if (status === "skipped") return "outline"
  return "destructive"
}

export function DeveloperTokenAutomotiveSheetSync() {
  const { t } = useTranslation()
  const [config, setConfig] = useState<AutomotiveSheetIntroSyncConfig>(() => defaultAutomotiveSheetIntroSyncConfig())
  const [tokens, setTokens] = useState<DeveloperTokenRecord[]>([])
  const [runs, setRuns] = useState<AutomotiveSheetIntroSyncRun[]>([])
  const [runsTotal, setRunsTotal] = useState(0)
  const [runsPage, setRunsPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [runsRefreshing, setRunsRefreshing] = useState(false)

  const fileSyncSummaryLabels = useMemo<FileSyncRuleSummaryLabels>(() => ({
    notConfigured: t("system.developerToken.fileSync.summary.notConfigured"),
    businessDomain: t("system.developerToken.fileSync.summary.businessDomain"),
    targetSpace: t("system.developerToken.fileSync.summary.targetSpace"),
    targetFolder: t("system.developerToken.fileSync.summary.targetFolder"),
    dynamicDepartment: t("system.developerToken.fileSync.summary.dynamicDepartment"),
    dynamicResponsiblePerson: t("system.developerToken.fileSync.summary.dynamicResponsiblePerson"),
    folderNone: t("system.developerToken.fileSync.summary.folderNone"),
    folderDynamicDepartmentName: t("system.developerToken.fileSync.summary.folderDynamicDepartmentName"),
    folderDynamicCallerMainDepartmentName: t("system.developerToken.fileSync.summary.folderDynamicCallerMainDepartmentName"),
    root: t("system.developerToken.fileSync.targetTree.root"),
    stale: t("system.developerToken.fileSync.targetTree.stale"),
  }), [t])

  const selectedToken = useMemo(
    () => tokens.find((item) => item.id === config.developer_token_id) ?? null,
    [config.developer_token_id, tokens],
  )

  const tokenFileSyncSummary = useMemo(
    () => formatFileSyncRuleSummary(
      selectedToken?.file_sync_rule,
      fileSyncSummaryLabels,
      selectedToken?.file_sync_target_display,
    ),
    [fileSyncSummaryLabels, selectedToken],
  )

  const loadRuns = useCallback(async (page: number, options?: { silent?: boolean }) => {
    if (!options?.silent) {
      setRunsRefreshing(true)
    }
    try {
      const runsResult = await listAutomotiveSheetIntroSyncRunsApi({ page, limit: RUNS_PAGE_SIZE })
      setRuns(runsResult.data)
      setRunsTotal(runsResult.total)
      setRunsPage(page)
      return runsResult
    } finally {
      if (!options?.silent) {
        setRunsRefreshing(false)
      }
    }
  }, [])

  const loadInitialData = useCallback(async () => {
    setLoading(true)
    try {
      const [configResult, tokenResult, runsResult] = await Promise.allSettled([
        getAutomotiveSheetIntroSyncConfigApi(),
        listDeveloperTokensApi({ limit: 200 }),
        listAutomotiveSheetIntroSyncRunsApi({ page: 1, limit: RUNS_PAGE_SIZE }),
      ])

      if (configResult.status === "fulfilled") {
        setConfig(configResult.value)
      }
      if (tokenResult.status === "fulfilled") {
        setTokens(tokenResult.value.data)
      } else {
        setTokens([])
      }
      if (runsResult.status === "fulfilled") {
        setRuns(runsResult.value.data)
        setRunsTotal(runsResult.value.total)
        setRunsPage(1)
      } else {
        setRuns([])
        setRunsTotal(0)
        setRunsPage(1)
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadInitialData()
  }, [loadInitialData])

  const refreshRuns = useCallback(async (page = runsPage) => {
    await loadRuns(page)
  }, [loadRuns, runsPage])

  const showValidationError = (field: string) => {
    toast({
      title: t("prompt"),
      variant: "error",
      description: t("system.developerToken.automotiveSheetIntro.invalidError", {
        field: t(`system.developerToken.automotiveSheetIntro.errorFields.${field}`),
      }),
    })
  }

  const handleSave = async () => {
    const normalized = normalizeAutomotiveSheetIntroSyncConfig(config)
    const invalid = findInvalidAutomotiveSheetIntroSyncConfig(normalized, selectedToken)
    if (invalid) {
      showValidationError(invalid.field)
      return
    }

    setSaving(true)
    try {
      const saved = await updateAutomotiveSheetIntroSyncConfigApi(normalized)
      setConfig(saved)
      toast({
        title: t("prompt"),
        variant: "success",
        description: t("system.developerToken.saved"),
      })
    } finally {
      setSaving(false)
    }
  }

  const handleTest = async () => {
    setTesting(true)
    try {
      const result = await testAutomotiveSheetIntroSyncApi()
      await loadRuns(1, { silent: true })

      const statusKey = result.status ?? "failed"
      const toastVariant = result.status === "success"
        ? "success"
        : result.status === "failed"
          ? "error"
          : "warning"
      const detail = result.error_message || result.skip_reason
      toast({
        title: t("prompt"),
        variant: toastVariant,
        description: detail
          ? t("system.developerToken.automotiveSheetIntro.testFinishedWithDetail", {
            status: t(`system.developerToken.automotiveSheetIntro.statuses.${statusKey}`),
            detail,
          })
          : t("system.developerToken.automotiveSheetIntro.testFinished", {
            status: t(`system.developerToken.automotiveSheetIntro.statuses.${statusKey}`),
          }),
      })
    } finally {
      setTesting(false)
    }
  }

  const accordionSummary = config.enabled
    ? t("system.developerToken.automotiveSheetIntro.summaryEnabled")
    : t("system.developerToken.automotiveSheetIntro.summaryDisabled")

  const configForm = (
    <>
      <div className="grid gap-3 md:grid-cols-2">
        <label className="flex items-center justify-between rounded-md border px-3 py-2 text-sm md:col-span-2">
          <span>{t("system.developerToken.automotiveSheetIntro.enabled")}</span>
          <Switch
            checked={config.enabled}
            onCheckedChange={(enabled) => setConfig((current) => ({ ...current, enabled }))}
          />
        </label>

        <label className="space-y-1 text-sm md:col-span-2">
          <span>{t("system.developerToken.automotiveSheetIntro.apiUrl")}</span>
          <Input
            value={config.api_url ?? ""}
            placeholder={t("system.developerToken.automotiveSheetIntro.apiUrlPlaceholder")}
            onChange={(event) => setConfig((current) => ({
              ...current,
              api_url: event.target.value || null,
            }))}
          />
        </label>

        <Field label={t("system.developerToken.automotiveSheetIntro.apiMethod")}>
          <Select
            value={config.api_method}
            onValueChange={(value) => setConfig((current) => ({
              ...current,
              api_method: value as AutomotiveSheetIntroSyncConfig["api_method"],
            }))}
          >
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="GET">GET</SelectItem>
              <SelectItem value="POST">POST</SelectItem>
            </SelectContent>
          </Select>
        </Field>

        <Field label={t("system.developerToken.automotiveSheetIntro.developerToken")}>
          <Select
            value={config.developer_token_id ? String(config.developer_token_id) : UNSET_VALUE}
            onValueChange={(value) => setConfig((current) => ({
              ...current,
              developer_token_id: value === UNSET_VALUE ? null : Number(value),
            }))}
          >
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value={UNSET_VALUE}>{t("system.developerToken.automotiveSheetIntro.selectToken")}</SelectItem>
              {tokens.map((token) => (
                <SelectItem
                  key={token.id}
                  value={String(token.id)}
                  disabled={!token.enabled}
                >
                  {token.name} ({token.token_prefix})
                  {!token.enabled ? ` · ${t("system.developerToken.disabled")}` : ""}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {tokens.length === 0 && (
            <p className="text-xs text-muted-foreground">
              {t("system.developerToken.automotiveSheetIntro.noTokensAvailable")}
            </p>
          )}
        </Field>

        <label className="space-y-1 text-sm md:col-span-2">
          <span>{t("system.developerToken.automotiveSheetIntro.fileName")}</span>
          <Input
            value={config.file_name}
            onChange={(event) => setConfig((current) => ({ ...current, file_name: event.target.value }))}
          />
        </label>

        {selectedToken ? (
          <div className="space-y-1 rounded-md border bg-muted/20 px-3 py-2 text-sm md:col-span-2">
            <div className="font-medium">
              {t("system.developerToken.automotiveSheetIntro.tokenFileSyncRule")}
            </div>
            <p className="text-xs text-muted-foreground">
              {t("system.developerToken.automotiveSheetIntro.tokenFileSyncRuleHint")}
            </p>
            <p className="text-xs">{tokenFileSyncSummary}</p>
            {!selectedToken.file_sync_rule && (
              <p className="text-xs text-destructive">
                {t("system.developerToken.automotiveSheetIntro.tokenFileSyncRuleMissing")}
              </p>
            )}
          </div>
        ) : (
          <p className="text-xs text-muted-foreground md:col-span-2">
            {t("system.developerToken.automotiveSheetIntro.selectTokenFirst")}
          </p>
        )}
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <Button disabled={saving} onClick={handleSave}>
          {t("system.developerToken.saveConfig")}
        </Button>
        <Button variant="outline" disabled={testing || !config.enabled} onClick={handleTest}>
          {testing
            ? t("system.developerToken.automotiveSheetIntro.testSyncRunning")
            : t("system.developerToken.automotiveSheetIntro.testSync")}
        </Button>
      </div>

      <div className="mt-4 space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="text-sm font-medium">
            {t("system.developerToken.automotiveSheetIntro.recentRuns", { total: runsTotal })}
          </div>
          <Button
            size="sm"
            variant="outline"
            disabled={runsRefreshing}
            onClick={() => {
              void refreshRuns()
            }}
          >
            {runsRefreshing
              ? t("system.developerToken.automotiveSheetIntro.refreshingRuns")
              : t("system.developerToken.automotiveSheetIntro.refreshRuns")}
          </Button>
        </div>
        {testing && (
          <p className="text-xs text-muted-foreground">
            {t("system.developerToken.automotiveSheetIntro.testRunning")}
          </p>
        )}
        {runs.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            {t("system.developerToken.automotiveSheetIntro.noRuns")}
          </p>
        ) : (
          <div className="overflow-x-auto rounded-md border">
            <table className="min-w-full text-sm">
              <thead className="bg-muted/40 text-left text-xs text-muted-foreground">
                <tr>
                  <th className="px-3 py-2">{t("system.developerToken.automotiveSheetIntro.runColumns.id")}</th>
                  <th className="px-3 py-2">{t("system.developerToken.automotiveSheetIntro.runColumns.trigger")}</th>
                  <th className="px-3 py-2">{t("system.developerToken.automotiveSheetIntro.runColumns.status")}</th>
                  <th className="px-3 py-2">{t("system.developerToken.automotiveSheetIntro.runColumns.fileName")}</th>
                  <th className="px-3 py-2">{t("system.developerToken.automotiveSheetIntro.runColumns.startTime")}</th>
                  <th className="px-3 py-2">{t("system.developerToken.automotiveSheetIntro.runColumns.duration")}</th>
                  <th className="px-3 py-2">{t("system.developerToken.automotiveSheetIntro.runColumns.error")}</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr key={run.id} className="border-t">
                    <td className="px-3 py-2">{run.id}</td>
                    <td className="px-3 py-2">
                      {t(`system.developerToken.automotiveSheetIntro.triggerTypes.${run.trigger_type}`)}
                    </td>
                    <td className="px-3 py-2">
                      <Badge variant={getRunStatusBadgeVariant(run.status)}>
                        {t(`system.developerToken.automotiveSheetIntro.statuses.${run.status}`)}
                      </Badge>
                    </td>
                    <td className="px-3 py-2">{run.file_name || "-"}</td>
                    <td className="px-3 py-2">{formatIsoDateTime(run.start_time)}</td>
                    <td className="px-3 py-2">
                      {run.duration_ms != null ? `${run.duration_ms} ms` : "-"}
                    </td>
                    <td className="max-w-xs truncate px-3 py-2" title={run.error_message || undefined}>
                      {run.error_message || "-"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {runsTotal > RUNS_PAGE_SIZE && (
          <AutoPagination
            className="justify-end"
            page={runsPage}
            pageSize={RUNS_PAGE_SIZE}
            total={runsTotal}
            onChange={(page) => {
              void loadRuns(page)
            }}
          />
        )}
      </div>
    </>
  )

  return (
    <section className="shrink-0 border-b pb-2">
      <Accordion type="single" collapsible className="w-full">
        <AccordionItem value="automotive-sheet-intro-sync" className="border-none">
          <AccordionTrigger className="py-3 hover:no-underline" hoverable>
            <div className="flex flex-1 flex-wrap items-center gap-2 pr-2 text-left">
              <span className="text-base font-medium">
                {t("system.developerToken.automotiveSheetIntro.title")}
              </span>
              <span className="text-xs text-muted-foreground">
                {loading ? t("system.developerToken.automotiveSheetIntro.loading") : accordionSummary}
              </span>
            </div>
          </AccordionTrigger>
          <AccordionContent className="pb-2">
            <p className="mb-4 text-xs text-muted-foreground">
              {t("system.developerToken.automotiveSheetIntro.description")}
            </p>
            {loading ? (
              <p className="text-sm text-muted-foreground">
                {t("system.developerToken.automotiveSheetIntro.loading")}
              </p>
            ) : (
              configForm
            )}
          </AccordionContent>
        </AccordionItem>
      </Accordion>
    </section>
  )
}

function Field({
  label,
  className,
  children,
}: {
  label: string
  className?: string
  children: ReactNode
}) {
  return (
    <div className={`space-y-1 text-sm${className ? ` ${className}` : ""}`}>
      <div>{label}</div>
      {children}
    </div>
  )
}
