import { isNumberDraftWithinBounds } from '@/utils/fieldValidation';
import { Button, Input, toast } from '@bisheng/ui';
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { RadioGroup,Radio as RadioGroupItem,Switch,Tag } from "@bisheng/ui";





import {
Table,
TableBody,
TableCell,
TableHead,
TableHeader,
TableRow,
} from "@/components/bs-ui/table";

import {
getPersonalTokenSettingApi,
listPersonalTokensApi,
revokePersonalTokenApi,
updatePersonalTokenSettingApi,
} from "@/controllers/API/personalToken";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import type { PersonalTokenDataScope,PersonalTokenLedgerItem,PersonalTokenSetting } from "@/types/api/openApi";
import { useCallback,useEffect,useState } from "react";
import { useTranslation } from "react-i18next";
import { OpenApiListFooter } from "../OpenApiList/OpenApiListFooter";
import { useOpenApiList } from "../OpenApiList/useOpenApiList";

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "-"
}

export function PersonalToken() {
  const { t } = useTranslation()
  const [setting, setSetting] = useState<PersonalTokenSetting | null>(null)
  const [enabled, setEnabled] = useState(false)
  const [ttlDays, setTtlDays] = useState(365)
  const [dataScope, setDataScope] = useState<PersonalTokenDataScope>("all_visible")
  const [saving, setSaving] = useState(false)
  const fetchPage = useCallback((page: number, pageSize: number) =>
    listPersonalTokensApi({ page, page_size: pageSize }), [])
  const list = useOpenApiList(fetchPage)
  const items = list.items

  const load = useCallback(async () => {
    const nextSetting = await captureAndAlertRequestErrorHoc(getPersonalTokenSettingApi())
    if (!nextSetting) return
    setSetting(nextSetting)
    setEnabled(nextSetting.pat_enabled)
    setTtlDays(nextSetting.pat_ttl_days)
    setDataScope(nextSetting.data_scope)
  }, [])

  useEffect(() => {
    void load()
  }, [load])

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
      toast.show({ type: "success", message: [String(t("prompt") ?? ''), String(t("openApiManagement.personalToken.settingsSaved") ?? '')].filter(Boolean).join('\n') })
    } finally {
      setSaving(false)
    }
  }

  const handleSave = () => {
        if ((String((ttlDays) ?? '') !== '' && (!Number.isFinite(Number(ttlDays)) || Number(ttlDays) < 1 || Number(ttlDays) > 365))) return;

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
        void captureAndAlertRequestErrorHoc(revokePersonalTokenApi(item.id).then(() => true))
          .then((success) => { if (success) void list.reload() })
      },
    })
  }

  return (
    <div className="h-full min-h-0 flex-1 space-y-5 overflow-y-auto pb-8">
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
            <Input type="number" min={1} max={365} value={ttlDays} disabled={saving} onChange={(event) => { if (!isNumberDraftWithinBounds(event.currentTarget.value, { min: 1, max: 365 })) return; return setTtlDays(Number(event.target.value)); }} />
          </label>
        </div>
        <div className="mt-4 space-y-2 text-sm">
          <p className="text-muted-foreground">{t("openApiManagement.personalToken.scopeModeLabel")}</p>
          <RadioGroup
            value={dataScope}
            disabled={saving}
            onValueChange={(value) => setDataScope(value as PersonalTokenDataScope)}
            className="items-start"
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
          <Button loading={saving} aria-busy={saving} onClick={handleSave} disabled={((String((ttlDays) ?? '') !== '' && (!Number.isFinite(Number(ttlDays)) || Number(ttlDays) < 1 || Number(ttlDays) > 365))) || (Boolean(saving) || (!setting?.deployment_enabled || ttlDays < 1 || ttlDays > 365))}>
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
                {item.holder_is_admin ? (
                  <span title={t("openApiManagement.personalToken.adminHolderTip")}>
                    <Tag size="small" className="ml-2">{t("openApiManagement.personalToken.adminHolder")}</Tag>
                  </span>
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
                <Button size="small" variant="link" color="danger" disabled={!item.is_valid} onClick={() => handleRevoke(item)}>{t("openApiManagement.actions.revoke")}</Button>
              </TableCell>
            </TableRow>
          ))}
          {list.isEmpty ? <TableRow><TableCell colSpan={8} className="text-center text-muted-foreground">{t("openApiManagement.empty")}</TableCell></TableRow> : null}
        </TableBody>
      </Table>
      <OpenApiListFooter status={list.status} itemCount={items.length} onLoadMore={list.loadMore} onRetry={list.retry} />
    </div>
  )
}
