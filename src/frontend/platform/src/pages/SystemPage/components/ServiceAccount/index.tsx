import { Badge } from "@/components/bs-ui/badge"
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
import { Button } from "@/components/bs-ui/button"
import { SearchInput } from "@/components/bs-ui/input"
import AutoPagination from "@/components/bs-ui/pagination/autoPagination"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/bs-ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/bs-ui/tabs"
import { message } from "@/components/bs-ui/toast/use-toast"
import { QuestionTooltip } from "@/components/bs-ui/tooltip"
import {
  deleteServiceAccountApi,
  getServiceAccountApi,
  listServiceAccountsApi,
  listServiceAccountResourceGrantsApi,
  setServiceAccountEnabledApi,
} from "@/controllers/API/serviceAccount"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import type { ServiceAccountDelegateScope, ServiceAccountItem } from "@/types/api/openApi"
import { Loader2 } from "lucide-react"
import { useCallback, useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { ApiKeysTab } from "./ApiKeysTab"
import { CreateServiceAccountDialog } from "./CreateServiceAccountDialog"
import { ResourceGrantsTab } from "./ResourceGrantsTab"

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "-"
}

const PAGE_SIZE = 20

export function ServiceAccount() {
  const { t } = useTranslation()
  const [accounts, setAccounts] = useState<ServiceAccountItem[]>([])
  const [selected, setSelected] = useState<ServiceAccountItem | null>(null)
  const [keyword, setKeyword] = useState("")
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [idleDays, setIdleDays] = useState(0)
  const [listLoading, setListLoading] = useState(true)
  const [createOpen, setCreateOpen] = useState(false)
  const [actionLoading, setActionLoading] = useState<"toggle" | "delete" | null>(null)
  const [initialTab, setInitialTab] = useState<"overview" | "keys">("overview")
  const [autoOpenIssue, setAutoOpenIssue] = useState(false)

  const loadList = useCallback(async (targetPage: number, targetKeyword: string) => {
    setListLoading(true)
    try {
      const result = await captureAndAlertRequestErrorHoc(listServiceAccountsApi({
        keyword: targetKeyword.trim() || undefined,
        page: targetPage,
        page_size: PAGE_SIZE,
      }))
      if (!result) return
      setAccounts(result.data)
      setTotal(result.total)
      setIdleDays(result.idle_days)
    } finally {
      setListLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadList(1, "")
  }, [loadList])

  const openDetail = async (id: number, tab: "overview" | "keys" = "overview") => {
    const account = await captureAndAlertRequestErrorHoc(getServiceAccountApi(id))
    if (account) {
      setInitialTab(tab)
      setAutoOpenIssue(tab === "keys")
      setSelected(account)
    }
  }

  const handleToggle = async () => {
    if (!selected) return
    const enabled = selected.status !== "enabled"
    setActionLoading("toggle")
    try {
      const account = await captureAndAlertRequestErrorHoc(setServiceAccountEnabledApi(selected.id, enabled))
      if (!account) return
      setSelected(account)
      message({ description: t(enabled ? "openApiManagement.feedback.enabled" : "openApiManagement.feedback.disabled") })
      await loadList(page, keyword)
    } finally {
      setActionLoading(null)
    }
  }

  const handleDelete = async () => {
    if (!selected) return
    const grants = await captureAndAlertRequestErrorHoc(listServiceAccountResourceGrantsApi(selected.id))
    if (!grants) return
    bsConfirm({
      desc: (
        <div className="space-y-2 text-left">
          <p>{t("openApiManagement.serviceAccount.deleteConfirm", { count: grants.length })}</p>
          {grants.length ? (
            <div>
              <p className="font-medium">{t("openApiManagement.serviceAccount.deleteGrantListTitle")}</p>
              <ul className="mt-1 max-h-40 list-disc overflow-y-auto pl-5">
                {grants.map((grant) => (
                  <li key={grant.assignee_id}>{grant.resource_name} · {grant.model_name}</li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="text-muted-foreground">{t("openApiManagement.serviceAccount.deleteNoGrants")}</p>
          )}
        </div>
      ),
      onOk: (close) => {
        close()
        setActionLoading("delete")
        void captureAndAlertRequestErrorHoc(deleteServiceAccountApi(selected.id))
          .then(async (result) => {
            if (!result) return
            setSelected(null)
            message({ description: t("openApiManagement.feedback.deleted") })
            await loadList(page, keyword)
          })
          .finally(() => setActionLoading(null))
      },
    })
  }

  const formatDelegateScope = (scope: ServiceAccountDelegateScope) => {
    const name = scope.subject_name || `${scope.subject_type}:${scope.subject_id}`
    return scope.subject_type === "department"
      ? t("openApiManagement.serviceAccount.departmentScope", { name })
      : name
  }

  const renderDelegateScopes = (account: ServiceAccountItem) => {
    if (!account.has_delegate) return "-"
    const displayed = account.delegate_scopes.slice(0, 2).map(formatDelegateScope)
    const remaining = account.delegate_scopes.length - displayed.length
    return (
      <span title={account.delegate_scopes.map(formatDelegateScope).join(", ")}>
        {displayed.join(", ")}
        {remaining > 0 ? t("openApiManagement.serviceAccount.moreScopes", { count: remaining }) : ""}
      </span>
    )
  }

  if (selected) {
    const isEnabled = selected.status === "enabled"
    return (
      <div className="min-h-0 flex-1 overflow-y-auto pb-8">
        <div className="mb-4 flex items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <Button variant="outline" size="sm" onClick={() => { setSelected(null); setAutoOpenIssue(false) }}>{t("openApiManagement.actions.back")}</Button>
            <div>
              <h2 className="text-lg font-semibold">{selected.name}</h2>
              <p className="text-sm text-muted-foreground">{selected.description || "-"}</p>
            </div>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" disabled={actionLoading !== null} onClick={handleToggle}>
              {actionLoading === "toggle" ? <Loader2 aria-hidden="true" className="mr-2 size-4 animate-spin" /> : null}
              {t(isEnabled ? "openApiManagement.actions.disable" : "openApiManagement.actions.enable")}
            </Button>
            <Button variant="destructive" disabled={actionLoading !== null} onClick={handleDelete}>
              {actionLoading === "delete" ? <Loader2 aria-hidden="true" className="mr-2 size-4 animate-spin" /> : null}
              {t("delete")}
            </Button>
          </div>
        </div>
        <Tabs defaultValue={initialTab}>
          <TabsList>
            <TabsTrigger value="overview">{t("openApiManagement.serviceAccount.overview")}</TabsTrigger>
            <TabsTrigger value="keys">{t("openApiManagement.serviceAccount.keys")}</TabsTrigger>
            <TabsTrigger value="grants">{t("openApiManagement.serviceAccount.grants")}</TabsTrigger>
          </TabsList>
          <TabsContent value="overview" className="space-y-3 rounded-md border p-4 text-sm">
            <p><span className="text-muted-foreground">{t("openApiManagement.fields.status")}: </span>{t(isEnabled ? "openApiManagement.status.enabled" : "openApiManagement.status.disabled")}</p>
            <p><span className="text-muted-foreground">{t("openApiManagement.fields.owner")}: </span>{selected.resource_owner.user_name || selected.resource_owner.user_id}</p>
            <p><span className="text-muted-foreground">{t("openApiManagement.fields.activeKeys")}: </span>{selected.active_key_count}</p>
            <p><span className="text-muted-foreground">{t("openApiManagement.fields.lastUsed")}: </span>{formatDate(selected.last_used_at)}</p>
          </TabsContent>
          <TabsContent value="keys"><ApiKeysTab serviceAccountId={selected.id} accountEnabled={isEnabled} initialIssueOpen={autoOpenIssue} /></TabsContent>
          <TabsContent value="grants"><ResourceGrantsTab serviceAccountId={selected.id} /></TabsContent>
        </Tabs>
      </div>
    )
  }

  return (
    <div className="min-h-0 flex-1 overflow-y-auto pb-8">
      <div className="mb-4 flex items-center justify-end gap-3">
        <SearchInput
          className="w-56"
          value={keyword}
          placeholder={t("openApiManagement.serviceAccount.search")}
          onChange={(event) => setKeyword(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              setPage(1)
              void loadList(1, keyword)
            }
          }}
        />
        <Button onClick={() => setCreateOpen(true)}>{t("openApiManagement.serviceAccount.create")}</Button>
      </div>
      <Table>
        <TableHeader><TableRow>
          <TableHead>{t("openApiManagement.fields.name")}</TableHead>
          <TableHead>{t("openApiManagement.fields.owner")}</TableHead>
          <TableHead>{t("openApiManagement.fields.status")}</TableHead>
          <TableHead>{t("openApiManagement.fields.activeKeys")}</TableHead>
          <TableHead>{t("openApiManagement.fields.delegate")}</TableHead>
          <TableHead>{t("openApiManagement.fields.lastUsed")}</TableHead>
          <TableHead>{t("openApiManagement.fields.creator")}</TableHead>
          <TableHead className="text-right">{t("operations")}</TableHead>
        </TableRow></TableHeader>
        <TableBody>
          {accounts.map((account) => {
            const isEnabled = account.status === "enabled"
            return (
              <TableRow key={account.id}>
                <TableCell>{account.name}</TableCell>
                <TableCell>
                  <span className={account.resource_owner.disabled ? "text-red-500" : ""}>
                    {account.resource_owner.user_name || account.resource_owner.user_id}
                  </span>
                  {account.resource_owner.disabled ? <QuestionTooltip error content={t("openApiManagement.serviceAccount.ownerDisabled")} /> : null}
                </TableCell>
                <TableCell><Badge variant={isEnabled ? "outline" : "secondary"}>{t(isEnabled ? "openApiManagement.status.enabled" : "openApiManagement.status.disabled")}</Badge></TableCell>
                <TableCell>
                  <span className={account.active_key_count === 0 ? "text-red-500" : ""}>{account.active_key_count}</span>
                  {account.active_key_count === 0 ? <QuestionTooltip error content={t("openApiManagement.serviceAccount.noKeyWarning")} /> : null}
                </TableCell>
                <TableCell className="max-w-56 truncate">{renderDelegateScopes(account)}</TableCell>
                <TableCell>
                  <span>{account.last_used_at ? formatDate(account.last_used_at) : t("openApiManagement.serviceAccount.neverUsed")}</span>
                  {account.idle ? <QuestionTooltip content={t("openApiManagement.serviceAccount.idleWarning", { days: idleDays })} /> : null}
                </TableCell>
                <TableCell>
                  <div>{account.creator_name || account.created_by || "-"}</div>
                  <div className="text-xs text-muted-foreground">{formatDate(account.create_time)}</div>
                </TableCell>
                <TableCell className="text-right"><Button variant="link" onClick={() => openDetail(account.id)}>{t("openApiManagement.actions.details")}</Button></TableCell>
              </TableRow>
            )
          })}
          {listLoading ? <TableRow><TableCell colSpan={8} className="py-8 text-center"><Loader2 aria-label={t("loading")} className="mx-auto size-5 animate-spin" /></TableCell></TableRow> : null}
          {!listLoading && !accounts.length ? <TableRow><TableCell colSpan={8} className="text-center text-muted-foreground">{t("openApiManagement.empty")}</TableCell></TableRow> : null}
        </TableBody>
      </Table>
      <AutoPagination
        className="mt-4 justify-end"
        page={page}
        pageSize={PAGE_SIZE}
        total={total}
        showTotal
        onChange={(nextPage) => {
          setPage(nextPage)
          void loadList(nextPage, keyword)
        }}
      />
      <CreateServiceAccountDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={(id) => { setPage(1); void loadList(1, keyword); void openDetail(id, "keys") }}
      />
    </div>
  )
}
