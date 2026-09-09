import { Badge } from "@/components/bs-ui/badge"
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
import { Button } from "@/components/bs-ui/button"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/bs-ui/table"
import { message } from "@/components/bs-ui/toast/use-toast"
import {
  listOpenApiScopesApi,
  listServiceAccountKeysApi,
  revokeAllServiceAccountKeysApi,
  revokeServiceAccountKeyApi,
} from "@/controllers/API/serviceAccount"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import type { ApiKeyItem, OpenApiScopeItem } from "@/types/api/openApi"
import { Loader2 } from "lucide-react"
import { useCallback, useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { KeyIssueDialog } from "./KeyIssueDialog"

export interface ApiKeysTabProps {
  serviceAccountId: number
  accountEnabled: boolean
  initialIssueOpen?: boolean
}

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "-"
}

export function ApiKeysTab({ serviceAccountId, accountEnabled, initialIssueOpen = false }: ApiKeysTabProps) {
  const { t } = useTranslation()
  const [keys, setKeys] = useState<ApiKeyItem[]>([])
  const [scopes, setScopes] = useState<OpenApiScopeItem[]>([])
  const [dialogOpen, setDialogOpen] = useState(initialIssueOpen)
  const [editingKey, setEditingKey] = useState<ApiKeyItem | null>(null)
  const [loading, setLoading] = useState(false)
  const [loadingData, setLoadingData] = useState(true)

  const loadKeys = useCallback(async () => {
    setLoadingData(true)
    try {
      const rows = await captureAndAlertRequestErrorHoc(listServiceAccountKeysApi(serviceAccountId))
      if (rows) setKeys(rows)
    } finally {
      setLoadingData(false)
    }
  }, [serviceAccountId])

  useEffect(() => {
    void loadKeys()
    void captureAndAlertRequestErrorHoc(listOpenApiScopesApi()).then((catalog) => {
      if (catalog) setScopes(catalog.scopes)
    })
  }, [loadKeys])

  const handleRevoke = (keyId: number) => {
    bsConfirm({
      desc: t("openApiManagement.keys.revokeConfirm"),
      onOk: (close) => {
        close()
        setLoading(true)
        void captureAndAlertRequestErrorHoc(revokeServiceAccountKeyApi(serviceAccountId, keyId))
          .then(async (result) => {
            if (!result) return
            message({ description: t("openApiManagement.feedback.keyRevoked") })
            await loadKeys()
          })
          .finally(() => setLoading(false))
      },
    })
  }

  const handleRevokeAll = () => {
    bsConfirm({
      desc: t("openApiManagement.keys.revokeAllConfirm"),
      onOk: (close) => {
        close()
        setLoading(true)
        void captureAndAlertRequestErrorHoc(revokeAllServiceAccountKeysApi(serviceAccountId))
          .then(async (result) => {
            if (!result) return
            const { revoked } = result
            message({ description: t("openApiManagement.feedback.keysRevoked", { count: revoked }) })
            await loadKeys()
          })
          .finally(() => setLoading(false))
      },
    })
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-end gap-2">
        <Button variant="outline" disabled={loading || loadingData || !keys.some((key) => key.is_valid)} onClick={handleRevokeAll}>
          {t("openApiManagement.actions.revokeAll")}
        </Button>
        <Button disabled={loading || loadingData || !accountEnabled} onClick={() => { setEditingKey(null); setDialogOpen(true) }}>{t("openApiManagement.keys.issue")}</Button>
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t("openApiManagement.fields.name")}</TableHead>
            <TableHead>{t("openApiManagement.keys.mask")}</TableHead>
            <TableHead>{t("openApiManagement.keys.permissions")}</TableHead>
            <TableHead>{t("openApiManagement.keys.delegateScopes")}</TableHead>
            <TableHead>{t("openApiManagement.fields.lastUsed")}</TableHead>
            <TableHead>{t("openApiManagement.fields.expiresAt")}</TableHead>
            <TableHead>{t("openApiManagement.fields.status")}</TableHead>
            <TableHead className="text-right">{t("operations")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {keys.map((key) => {
            const statusKey = key.is_valid ? "active" : key.revoked_at ? "revoked" : "expired"
            return <TableRow key={key.id}>
              <TableCell>{key.name}</TableCell>
              <TableCell><code>{key.key_mask}</code></TableCell>
              <TableCell>{key.scopes.join(", ")}</TableCell>
              <TableCell>{key.delegate_scopes.map((scope) => {
                const name = scope.subject_name || `${scope.subject_type}:${scope.subject_id}`
                return scope.subject_type === "department"
                  ? t("openApiManagement.serviceAccount.departmentScope", { name })
                  : name
              }).join(", ") || "-"}</TableCell>
              <TableCell>{formatDate(key.last_used_at)}</TableCell>
              <TableCell>{formatDate(key.expires_at)}</TableCell>
              <TableCell><Badge variant={key.is_valid ? "outline" : "secondary"}>{t(`openApiManagement.status.${statusKey}`)}</Badge></TableCell>
              <TableCell className="text-right">
                <Button variant="link" disabled={loading || !key.is_valid} onClick={() => { setEditingKey(key); setDialogOpen(true) }}>
                  {t("edit")}
                </Button>
                <Button variant="link" disabled={loading || !key.is_valid} onClick={() => handleRevoke(key.id)}>
                  {t("openApiManagement.actions.revoke")}
                </Button>
              </TableCell>
            </TableRow>
          })}
          {loadingData ? (
            <TableRow><TableCell colSpan={8} className="py-8 text-center"><Loader2 aria-label={t("loading")} className="mx-auto size-5 animate-spin" /></TableCell></TableRow>
          ) : null}
          {!loadingData && !keys.length ? (
            <TableRow><TableCell colSpan={8} className="text-center text-muted-foreground">{t("openApiManagement.empty")}</TableCell></TableRow>
          ) : null}
        </TableBody>
      </Table>
      <KeyIssueDialog
        serviceAccountId={serviceAccountId}
        scopes={scopes}
        editingKey={editingKey}
        open={dialogOpen}
        onOpenChange={(nextOpen) => {
          setDialogOpen(nextOpen)
          if (!nextOpen) setEditingKey(null)
        }}
        onIssued={loadKeys}
      />
    </div>
  )
}
