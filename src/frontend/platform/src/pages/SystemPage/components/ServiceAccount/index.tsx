import { Badge } from "@/components/bs-ui/badge"
import { Button } from "@/components/bs-ui/button"
import { SearchInput } from "@/components/bs-ui/input"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/bs-ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/bs-ui/tabs"
import {
  deleteServiceAccountApi,
  getServiceAccountApi,
  listServiceAccountsApi,
  setServiceAccountEnabledApi,
} from "@/controllers/API/serviceAccount"
import type { ServiceAccountItem } from "@/types/api/openApi"
import { useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { ApiKeysTab } from "./ApiKeysTab"
import { CreateServiceAccountDialog } from "./CreateServiceAccountDialog"
import { ResourceGrantsTab } from "./ResourceGrantsTab"

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "-"
}

export function ServiceAccount() {
  const { t } = useTranslation()
  const [accounts, setAccounts] = useState<ServiceAccountItem[]>([])
  const [selected, setSelected] = useState<ServiceAccountItem | null>(null)
  const [keyword, setKeyword] = useState("")
  const [createOpen, setCreateOpen] = useState(false)

  const loadList = async () => {
    const page = await listServiceAccountsApi({ keyword: keyword.trim() || undefined, page: 1, page_size: 200 })
    setAccounts(page.data)
  }

  useEffect(() => {
    void listServiceAccountsApi({ page: 1, page_size: 200 }).then((page) => setAccounts(page.data))
  }, [])

  const openDetail = async (id: number) => setSelected(await getServiceAccountApi(id))

  const handleToggle = async () => {
    if (!selected) return
    const account = await setServiceAccountEnabledApi(selected.id, selected.status !== "active")
    setSelected(account)
    await loadList()
  }

  const handleDelete = async () => {
    if (!selected) return
    await deleteServiceAccountApi(selected.id)
    setSelected(null)
    await loadList()
  }

  if (selected) {
    return (
      <div className="min-h-0 flex-1 overflow-y-auto pb-8">
        <div className="mb-4 flex items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <Button variant="outline" size="sm" onClick={() => setSelected(null)}>{t("openApiManagement.actions.back")}</Button>
            <div>
              <h2 className="text-lg font-semibold">{selected.name}</h2>
              <p className="text-sm text-muted-foreground">{selected.description || "-"}</p>
            </div>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" onClick={handleToggle}>
              {t(selected.status === "active" ? "openApiManagement.actions.disable" : "openApiManagement.actions.enable")}
            </Button>
            <Button variant="destructive" onClick={handleDelete}>{t("delete")}</Button>
          </div>
        </div>
        <Tabs defaultValue="overview">
          <TabsList>
            <TabsTrigger value="overview">{t("openApiManagement.serviceAccount.overview")}</TabsTrigger>
            <TabsTrigger value="keys">{t("openApiManagement.serviceAccount.keys")}</TabsTrigger>
            <TabsTrigger value="grants">{t("openApiManagement.serviceAccount.grants")}</TabsTrigger>
          </TabsList>
          <TabsContent value="overview" className="space-y-3 rounded-md border p-4 text-sm">
            <p><span className="text-muted-foreground">{t("openApiManagement.fields.status")}: </span>{t(selected.status === "active" ? "openApiManagement.status.active" : "openApiManagement.status.disabled")}</p>
            <p><span className="text-muted-foreground">{t("openApiManagement.fields.owner")}: </span>{selected.resource_owner.user_name || selected.resource_owner.user_id}</p>
            <p><span className="text-muted-foreground">{t("openApiManagement.fields.activeKeys")}: </span>{selected.active_key_count}</p>
            <p><span className="text-muted-foreground">{t("openApiManagement.fields.lastUsed")}: </span>{formatDate(selected.last_used_at)}</p>
          </TabsContent>
          <TabsContent value="keys"><ApiKeysTab serviceAccountId={selected.id} /></TabsContent>
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
          onKeyDown={(event) => { if (event.key === "Enter") void loadList() }}
        />
        <Button onClick={() => setCreateOpen(true)}>{t("openApiManagement.serviceAccount.create")}</Button>
      </div>
      <Table>
        <TableHeader><TableRow>
          <TableHead>{t("openApiManagement.fields.name")}</TableHead>
          <TableHead>{t("openApiManagement.fields.owner")}</TableHead>
          <TableHead>{t("openApiManagement.fields.status")}</TableHead>
          <TableHead>{t("openApiManagement.fields.activeKeys")}</TableHead>
          <TableHead>{t("openApiManagement.fields.lastUsed")}</TableHead>
          <TableHead className="text-right">{t("operations")}</TableHead>
        </TableRow></TableHeader>
        <TableBody>
          {accounts.map((account) => (
            <TableRow key={account.id}>
              <TableCell>{account.name}</TableCell>
              <TableCell>{account.resource_owner.user_name || account.resource_owner.user_id}</TableCell>
              <TableCell><Badge variant={account.status === "active" ? "outline" : "secondary"}>{t(account.status === "active" ? "openApiManagement.status.active" : "openApiManagement.status.disabled")}</Badge></TableCell>
              <TableCell>{account.active_key_count}</TableCell>
              <TableCell>{formatDate(account.last_used_at)}</TableCell>
              <TableCell className="text-right"><Button variant="link" onClick={() => openDetail(account.id)}>{t("openApiManagement.actions.details")}</Button></TableCell>
            </TableRow>
          ))}
          {!accounts.length ? <TableRow><TableCell colSpan={6} className="text-center text-muted-foreground">{t("openApiManagement.empty")}</TableCell></TableRow> : null}
        </TableBody>
      </Table>
      <CreateServiceAccountDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={(id) => { void loadList(); void openDetail(id) }}
      />
    </div>
  )
}
