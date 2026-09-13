import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
import { Badge } from "@/components/bs-ui/badge"
import { Button, LoadButton } from "@/components/bs-ui/button"
import { Input } from "@/components/bs-ui/input"
import AutoPagination from "@/components/bs-ui/pagination/autoPagination"
import { RadioGroup, RadioGroupItem } from "@/components/bs-ui/radio-group"
import { Switch } from "@/components/bs-ui/switch"
import { message } from "@/components/bs-ui/toast/use-toast"
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
  updatePersonalTokenSettingApi,
} from "@/controllers/API/personalToken"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import type { PersonalTokenDataScope, PersonalTokenSetting } from "@/types/api/openApi"
import type { PersonalTokenLedgerItem } from "@/types/api/openApi"
import { useEffect, useState } from "react"
import { useTranslation } from "react-i18next"

const PAGE_SIZE = 20

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "-"
}

export function PersonalToken() {
  const { t } = useTranslation()
  const [setting, setSetting] = useState<PersonalTokenSetting | null>(null)
  const [items, setItems] = useState<PersonalTokenLedgerItem[]>([])
  const [enabled, setEnabled] = useState(false)
  const [ttlDays, setTtlDays] = useState(365)
  const [dataScope, setDataScope] = useState<PersonalTokenDataScope>("all_visible")
  const [saving, setSaving] = useState(false)
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)

  const loadLedger = async (nextPage: number) => {
    const ledger = await listPersonalTokensApi({ page: nextPage, page_size: PAGE_SIZE })
    setItems(ledger.data)
    setTotal(ledger.total)
    setPage(nextPage)
  }

  const load = async () => {
    const nextSetting = await getPersonalTokenSettingApi()
    setSetting(nextSetting)
    setEnabled(nextSetting.pat_enabled)
    setTtlDays(nextSetting.pat_ttl_days)
    setDataScope(nextSetting.data_scope)
    await loadLedger(1)
  }

  useEffect(() => {
    void load()
  }, [])

  const applySetting = (next: PersonalTokenSetting) => {
    setSetting(next)
    setEnabled(next.pat_enabled)
    setTtlDays(next.pat_ttl_days)
    setDataScope(next.data_scope)
  }

  const doSave = async () => {
    setSaving(true)
    try {
      const next = await captureAndAlertRequestErrorHoc(
        updatePersonalTokenSettingApi({ pat_enabled: enabled, pat_ttl_days: ttlDays, data_scope: dataScope }),
      )
      if (!next) return

      applySetting(next)
      message({
        title: t("prompt"),
        variant: "success",
        description: t("openApiManagement.personalToken.settingsSaved"),
      })
    } finally {
      setSaving(false)
    }
  }

  const handleSave = () => {
    if (saving) return
    // Narrowing hits every issued key immediately — confirm before tightening;
    // widening back needs no ceremony.
    if (dataScope === "personal_only" && setting?.data_scope !== "personal_only") {
      bsConfirm({
        title: t("openApiManagement.personalToken.tightenConfirmTitle"),
        desc: t("openApiManagement.personalToken.tightenConfirmBody"),
        okTxt: t("openApiManagement.personalToken.tightenConfirmOk"),
        onOk: (close) => {
          close()
          void doSave()
        },
      })
      return
    }
    void doSave()
  }

  const handleRevoke = (item: PersonalTokenLedgerItem) => {
    bsConfirm({
      title: t("openApiManagement.personalToken.revokeConfirmTitle"),
      desc: t("openApiManagement.personalToken.revokeConfirmBody"),
      okTxt: t("openApiManagement.actions.revoke"),
      onOk: (close) => {
        close()
        void captureAndAlertRequestErrorHoc(revokePersonalTokenApi(item.id)).then(() => loadLedger(page))
      },
    })
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
            <Switch checked={enabled} disabled={!setting?.deployment_enabled || saving} onCheckedChange={setEnabled} />
            {t("openApiManagement.personalToken.tenantEnabled")}
          </label>
          <label className="w-48 space-y-1 text-sm">
            <span>{t("openApiManagement.personalToken.ttlDays")}</span>
            <Input type="number" min={1} max={365} value={ttlDays} disabled={saving} onChange={(event) => setTtlDays(Number(event.target.value))} />
          </label>
        </div>
        <div className="mt-4 space-y-2 text-sm">
          <p className="text-muted-foreground">{t("openApiManagement.personalToken.scopeModeLabel")}</p>
          <RadioGroup
            value={dataScope}
            disabled={saving}
            onValueChange={(value) => setDataScope(value as PersonalTokenDataScope)}
            className="space-y-2"
          >
            <label className="flex items-start gap-2">
              <RadioGroupItem value="all_visible" className="mt-0.5" />
              <span>{t("openApiManagement.personalToken.scopeModeAll")}</span>
            </label>
            <label className="flex items-start gap-2">
              <RadioGroupItem value="personal_only" className="mt-0.5" />
              <span>
                {t("openApiManagement.personalToken.scopeModeOwnOnly")}
                <span className="block text-xs text-muted-foreground">{t("openApiManagement.personalToken.scopeModeOwnOnlyHint")}</span>
              </span>
            </label>
          </RadioGroup>
        </div>
        <div className="mt-4">
          <LoadButton
            loading={saving}
            aria-busy={saving}
            disabled={!setting?.deployment_enabled || ttlDays < 1 || ttlDays > 365}
            onClick={handleSave}
          >
            {t("save")}
          </LoadButton>
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
                {item.holder_is_admin ? (
                  <Badge
                    className="ml-2"
                    variant="secondary"
                    title={t("openApiManagement.personalToken.adminHolderTip")}
                  >
                    {t("openApiManagement.personalToken.adminHolder")}
                  </Badge>
                ) : null}
              </TableCell>
              <TableCell><code>{item.key_mask}</code></TableCell>
              <TableCell>
                <div className="flex flex-wrap gap-1">
                  {item.scopes.map((scope) => (
                    <span
                      key={scope}
                      className="rounded bg-muted px-1.5 py-0.5 text-xs"
                    >
                      {t(
                        `openApiManagement.scopes.${scope.replace(":", "_")}.label`,
                        { defaultValue: scope },
                      )}
                    </span>
                  ))}
                </div>
              </TableCell>
              <TableCell>{formatDate(item.create_time)}</TableCell>
              <TableCell>{formatDate(item.last_used_at)}</TableCell>
              <TableCell>{formatDate(item.expires_at)}</TableCell>
              <TableCell>{t(item.is_valid ? "openApiManagement.status.active" : "openApiManagement.status.revoked")}</TableCell>
              <TableCell className="whitespace-nowrap text-right">
                <Button variant="link" disabled={!item.is_valid} onClick={() => handleRevoke(item)}>{t("openApiManagement.actions.revoke")}</Button>
              </TableCell>
            </TableRow>
          ))}
          {!items.length ? <TableRow><TableCell colSpan={8} className="text-center text-muted-foreground">{t("openApiManagement.empty")}</TableCell></TableRow> : null}
        </TableBody>
      </Table>
      {total > PAGE_SIZE ? (
        <AutoPagination
          page={page}
          pageSize={PAGE_SIZE}
          total={total}
          onChange={(nextPage) => void loadLedger(nextPage)}
        />
      ) : null}
    </div>
  )
}
