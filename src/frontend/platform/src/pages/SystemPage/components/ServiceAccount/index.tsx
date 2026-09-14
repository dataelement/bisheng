import { Badge } from "@/components/bs-ui/badge"
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
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/bs-ui/tabs"
import { QuestionTooltip } from "@/components/bs-ui/tooltip"
import {
  getServiceAccountApi,
  listServiceAccountsApi,
} from "@/controllers/API/serviceAccount"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import type {
  ServiceAccountDelegateScope,
  ServiceAccountItem,
} from "@/types/api/openApi"
import { formatIsoDateTime } from "@/util/utils"
import { ChevronLeft, Loader2 } from "lucide-react"
import { useCallback, useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { ApiKeysTab } from "./ApiKeysTab"
import { CreateServiceAccountDialog } from "./CreateServiceAccountDialog"
import { OverviewTab } from "./OverviewTab"
import { ResourceGrantsTab } from "./ResourceGrantsTab"

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
  const [initialTab, setInitialTab] = useState<"overview" | "keys">("overview")
  const [autoOpenIssue, setAutoOpenIssue] = useState(false)

  const loadList = useCallback(
    async (targetPage: number, targetKeyword: string) => {
      setListLoading(true)
      try {
        const result = await captureAndAlertRequestErrorHoc(
          listServiceAccountsApi({
            keyword: targetKeyword.trim() || undefined,
            page: targetPage,
            page_size: PAGE_SIZE,
          }),
        )
        if (!result) return
        setAccounts(result.data)
        setTotal(result.total)
        setIdleDays(result.idle_days)
      } finally {
        setListLoading(false)
      }
    },
    [],
  )

  useEffect(() => {
    void loadList(1, "")
  }, [loadList])

  const openDetail = async (
    id: number,
    tab: "overview" | "keys" = "overview",
  ) => {
    const account = await captureAndAlertRequestErrorHoc(
      getServiceAccountApi(id),
    )
    if (account) {
      setInitialTab(tab)
      setAutoOpenIssue(tab === "keys")
      setSelected(account)
    }
  }

  const formatDelegateScope = (scope: ServiceAccountDelegateScope) => {
    const name =
      scope.subject_name || `${scope.subject_type}:${scope.subject_id}`
    return scope.subject_type === "department"
      ? t("openApiManagement.serviceAccount.departmentScope", { name })
      : name
  }

  const renderDelegateScopes = (account: ServiceAccountItem) => {
    if (!account.has_delegate) return "-"
    const displayed = account.delegate_scopes
      .slice(0, 2)
      .map(formatDelegateScope)
    const remaining = account.delegate_scopes.length - displayed.length
    return (
      <span title={account.delegate_scopes.map(formatDelegateScope).join(", ")}>
        {displayed.join(", ")}
        {remaining > 0
          ? t("openApiManagement.serviceAccount.moreScopes", {
              count: remaining,
            })
          : ""}
      </span>
    )
  }

  if (selected) {
    const isEnabled = selected.status === "enabled"
    return (
      <div className="min-h-0 flex-1 overflow-y-auto pb-8">
        <div className="mb-4 flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            className="px-1"
            onClick={() => {
              setSelected(null)
              setAutoOpenIssue(false)
            }}
          >
            <ChevronLeft aria-hidden="true" className="mr-1 size-4" />
            {t("openApiManagement.actions.back")}
          </Button>
          <h2 className="truncate text-lg font-medium">{selected.name}</h2>
          <span className="text-sm text-muted-foreground">
            {t(`openApiManagement.status.${selected.status}`)}
          </span>
        </div>
        <Tabs defaultValue={initialTab}>
          <TabsList>
            <TabsTrigger value="overview">
              {t("openApiManagement.serviceAccount.overview")}
            </TabsTrigger>
            <TabsTrigger value="keys">
              {t("openApiManagement.serviceAccount.keys")}
            </TabsTrigger>
            <TabsTrigger value="grants">
              {t("openApiManagement.serviceAccount.grants")}
            </TabsTrigger>
          </TabsList>
          <TabsContent value="overview">
            <OverviewTab
              detail={selected}
              onChanged={(updated) => {
                setSelected(updated)
                void loadList(page, keyword)
              }}
              onDeleted={() => {
                setSelected(null)
                void loadList(page, keyword)
              }}
            />
          </TabsContent>
          <TabsContent value="keys">
            <ApiKeysTab
              serviceAccountId={selected.id}
              accountEnabled={isEnabled}
              initialIssueOpen={autoOpenIssue}
              onKeysChanged={() => {
                void captureAndAlertRequestErrorHoc(
                  getServiceAccountApi(selected.id),
                ).then((updated) => {
                  if (updated) setSelected(updated)
                })
                void loadList(page, keyword)
              }}
            />
          </TabsContent>
          <TabsContent value="grants">
            <ResourceGrantsTab
              serviceAccountId={selected.id}
              serviceAccountName={selected.name}
            />
          </TabsContent>
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
        <Button onClick={() => setCreateOpen(true)}>
          {t("openApiManagement.serviceAccount.create")}
        </Button>
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t("openApiManagement.fields.name")}</TableHead>
            <TableHead>{t("openApiManagement.fields.status")}</TableHead>
            <TableHead>{t("openApiManagement.fields.activeKeys")}</TableHead>
            <TableHead>{t("openApiManagement.fields.delegate")}</TableHead>
            <TableHead>{t("openApiManagement.fields.owner")}</TableHead>
            <TableHead>{t("openApiManagement.fields.lastUsed")}</TableHead>
            <TableHead>{t("openApiManagement.fields.creator")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {accounts.map((account) => {
            const isEnabled = account.status === "enabled"
            return (
              <TableRow key={account.id}>
                <TableCell>
                  <Button
                    variant="link"
                    className="h-auto max-w-56 px-0 font-medium"
                    onClick={() => openDetail(account.id)}
                  >
                    <span className="truncate">{account.name}</span>
                  </Button>
                </TableCell>
                <TableCell>
                  <Badge variant={isEnabled ? "outline" : "secondary"}>
                    {t(
                      isEnabled
                        ? "openApiManagement.status.enabled"
                        : "openApiManagement.status.disabled",
                    )}
                  </Badge>
                </TableCell>
                <TableCell>
                  <span
                    className={
                      account.active_key_count === 0 ? "text-red-500" : ""
                    }
                  >
                    {account.active_key_count}
                  </span>
                  {account.active_key_count === 0 ? (
                    <QuestionTooltip
                      error
                      content={t(
                        "openApiManagement.serviceAccount.noKeyWarning",
                      )}
                    />
                  ) : null}
                </TableCell>
                <TableCell className="max-w-56 truncate">
                  {renderDelegateScopes(account)}
                </TableCell>
                <TableCell>
                  <span
                    className={
                      account.resource_owner.disabled ? "text-red-500" : ""
                    }
                  >
                    {account.resource_owner.user_name ||
                      account.resource_owner.user_id}
                  </span>
                  {account.resource_owner.disabled ? (
                    <QuestionTooltip
                      error
                      content={t(
                        "openApiManagement.serviceAccount.ownerDisabled",
                      )}
                    />
                  ) : null}
                </TableCell>
                <TableCell>
                  <span>
                    {account.last_used_at
                      ? formatIsoDateTime(account.last_used_at)
                      : t("openApiManagement.serviceAccount.neverUsed")}
                  </span>
                  {account.idle ? (
                    <QuestionTooltip
                      content={t(
                        "openApiManagement.serviceAccount.idleWarning",
                        { days: idleDays },
                      )}
                    />
                  ) : null}
                </TableCell>
                <TableCell>
                  <div>{account.creator_name || account.created_by || "-"}</div>
                  <div className="text-xs text-muted-foreground">
                    {formatIsoDateTime(account.create_time)}
                  </div>
                </TableCell>
              </TableRow>
            )
          })}
          {listLoading ? (
            <TableRow>
              <TableCell colSpan={7} className="py-8 text-center">
                <Loader2
                  aria-label={t("loading")}
                  className="mx-auto size-5 animate-spin"
                />
              </TableCell>
            </TableRow>
          ) : null}
          {!listLoading && !accounts.length ? (
            <TableRow>
              <TableCell
                colSpan={7}
                className="text-center text-muted-foreground"
              >
                {t("openApiManagement.empty")}
              </TableCell>
            </TableRow>
          ) : null}
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
        onCreated={(id) => {
          setPage(1)
          void loadList(1, keyword)
          void openDetail(id, "keys")
        }}
      />
    </div>
  )
}
