import { Badge } from "@/components/bs-ui/badge"
import { Button } from "@/components/bs-ui/button"
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
import {
  getPersonalTokenSettingApi,
  listPersonalTokensApi,
  revokePersonalTokenApi,
  revokePersonalTokensByHolderApi,
  updatePersonalTokenSettingApi,
} from "@/controllers/API/personalToken"
import type { PersonalTokenLedgerItem, PersonalTokenSetting } from "@/types/api/openApi"
import { useEffect, useState } from "react"
import { useTranslation } from "react-i18next"

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "-"
}

export function PersonalToken() {
  const { t } = useTranslation()
  const [setting, setSetting] = useState<PersonalTokenSetting | null>(null)
  const [items, setItems] = useState<PersonalTokenLedgerItem[]>([])
  const [enabled, setEnabled] = useState(false)
  const [ttlDays, setTtlDays] = useState(30)

  const load = async () => {
    const [nextSetting, page] = await Promise.all([
      getPersonalTokenSettingApi(),
      listPersonalTokensApi({ page: 1, page_size: 200 }),
    ])
    setSetting(nextSetting)
    setEnabled(nextSetting.pat_enabled)
    setTtlDays(nextSetting.pat_ttl_days)
    setItems(page.data)
  }

  useEffect(() => {
    void load()
  }, [])

  const handleSave = async () => {
    const next = await updatePersonalTokenSettingApi({ pat_enabled: enabled, pat_ttl_days: ttlDays })
    setSetting(next)
    setEnabled(next.pat_enabled)
    setTtlDays(next.pat_ttl_days)
  }

  const handleRevoke = async (id: number) => {
    await revokePersonalTokenApi(id)
    await load()
  }

  const handleRevokeHolder = async (userId: number) => {
    await revokePersonalTokensByHolderApi(userId)
    await load()
  }

  return (
    <div className="min-h-0 flex-1 space-y-5 overflow-y-auto pb-8">
      <section className="rounded-md border p-4">
        <div className="mb-4">
          <h2 className="font-semibold">{t("openApiManagement.personalToken.settings")}</h2>
          {!setting?.deployment_enabled ? (
            <p className="mt-1 text-sm text-muted-foreground">{t("openApiManagement.personalToken.deploymentDisabled")}</p>
          ) : null}
        </div>
        <div className="flex flex-wrap items-end gap-6">
          <label className="flex items-center gap-2 text-sm">
            <Switch checked={enabled} disabled={!setting?.deployment_enabled} onCheckedChange={setEnabled} />
            {t("openApiManagement.personalToken.tenantEnabled")}
          </label>
          <label className="w-48 space-y-1 text-sm">
            <span>{t("openApiManagement.personalToken.ttlDays")}</span>
            <Input type="number" min={1} max={365} value={ttlDays} onChange={(event) => setTtlDays(Number(event.target.value))} />
          </label>
          <Button disabled={!setting?.deployment_enabled || ttlDays < 1 || ttlDays > 365} onClick={handleSave}>
            {t("save")}
          </Button>
        </div>
      </section>
      <Table>
        <TableHeader><TableRow>
          <TableHead>{t("openApiManagement.personalToken.holder")}</TableHead>
          <TableHead>{t("openApiManagement.keys.mask")}</TableHead>
          <TableHead>{t("openApiManagement.keys.permissions")}</TableHead>
          <TableHead>{t("openApiManagement.fields.createdAt")}</TableHead>
          <TableHead>{t("openApiManagement.fields.lastUsed")}</TableHead>
          <TableHead>{t("openApiManagement.fields.expiresAt")}</TableHead>
          <TableHead>{t("openApiManagement.fields.status")}</TableHead>
          <TableHead className="text-right">{t("operations")}</TableHead>
        </TableRow></TableHeader>
        <TableBody>
          {items.map((item) => (
            <TableRow key={item.id}>
              <TableCell>
                {item.holder_name || item.holder_user_id}
                {item.holder_is_admin ? <Badge className="ml-2" variant="secondary">{t("openApiManagement.personalToken.adminRisk")}</Badge> : null}
              </TableCell>
              <TableCell><code>{item.key_mask}</code></TableCell>
              <TableCell>{item.scopes.join(", ")}</TableCell>
              <TableCell>{formatDate(item.create_time)}</TableCell>
              <TableCell>{formatDate(item.last_used_at)}</TableCell>
              <TableCell>{formatDate(item.expires_at)}</TableCell>
              <TableCell>{t(item.is_valid ? "openApiManagement.status.active" : "openApiManagement.status.revoked")}</TableCell>
              <TableCell className="whitespace-nowrap text-right">
                <Button variant="link" disabled={!item.is_valid} onClick={() => handleRevoke(item.id)}>{t("openApiManagement.actions.revoke")}</Button>
                <Button variant="link" disabled={!item.is_valid} onClick={() => handleRevokeHolder(item.holder_user_id)}>{t("openApiManagement.actions.revokeHolder")}</Button>
              </TableCell>
            </TableRow>
          ))}
          {!items.length ? <TableRow><TableCell colSpan={8} className="text-center text-muted-foreground">{t("openApiManagement.empty")}</TableCell></TableRow> : null}
        </TableBody>
      </Table>
    </div>
  )
}
