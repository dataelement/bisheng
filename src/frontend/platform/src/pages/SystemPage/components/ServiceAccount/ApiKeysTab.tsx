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
import { toast } from "@/components/bs-ui/toast/use-toast"
import {
  listOpenApiScopesApi,
  listServiceAccountKeysApi,
  revokeAllServiceAccountKeysApi,
  revokeServiceAccountKeyApi,
} from "@/controllers/API/serviceAccount"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import type {
  ApiKeyIssued,
  ApiKeyItem,
  OpenApiScopeItem,
} from "@/types/api/openApi"
import { formatIsoDateTime } from "@/util/utils"
import { Loader2 } from "lucide-react"
import { useCallback, useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { KeyIssueDialog } from "./KeyIssueDialog"
import { KeyRevealDialog } from "./KeyRevealDialog"

export interface ApiKeysTabProps {
  serviceAccountId: number
  accountEnabled: boolean
  initialIssueOpen?: boolean
  onKeysChanged?: () => void
}

export function ApiKeysTab({
  serviceAccountId,
  accountEnabled,
  initialIssueOpen = false,
  onKeysChanged,
}: ApiKeysTabProps) {
  const { t } = useTranslation()
  const [keys, setKeys] = useState<ApiKeyItem[]>([])
  const [scopes, setScopes] = useState<OpenApiScopeItem[]>([])
  const [dialogOpen, setDialogOpen] = useState(initialIssueOpen)
  const [editingKey, setEditingKey] = useState<ApiKeyItem | null>(null)
  const [issuedKey, setIssuedKey] = useState<ApiKeyIssued | null>(null)
  const [loading, setLoading] = useState(false)
  const [loadingData, setLoadingData] = useState(true)
  const [loadingScopes, setLoadingScopes] = useState(true)

  const loadKeys = useCallback(async () => {
    setLoadingData(true)
    try {
      const rows = await captureAndAlertRequestErrorHoc(
        listServiceAccountKeysApi(serviceAccountId),
      )
      if (rows) setKeys(rows)
    } finally {
      setLoadingData(false)
    }
  }, [serviceAccountId])

  useEffect(() => {
    void loadKeys()
    setLoadingScopes(true)
    void captureAndAlertRequestErrorHoc(listOpenApiScopesApi())
      .then((catalog) => {
        if (catalog) setScopes(catalog.scopes)
      })
      .finally(() => setLoadingScopes(false))
  }, [loadKeys])

  const handleRevoke = (keyId: number) => {
    bsConfirm({
      title: t("openApiManagement.keys.revokeConfirmTitle"),
      desc: t("openApiManagement.keys.revokeConfirm"),
      okTxt: t("openApiManagement.actions.revoke"),
      onOk: (close) => {
        close()
        setLoading(true)
        void captureAndAlertRequestErrorHoc(
          revokeServiceAccountKeyApi(serviceAccountId, keyId),
        )
          .then(async (result) => {
            if (!result) return
            toast({
              title: t("openApiManagement.keys.revokeConfirmTitle"),
              description: t("openApiManagement.feedback.keyRevoked"),
              variant: "success",
            })
            await loadKeys()
            onKeysChanged?.()
          })
          .finally(() => setLoading(false))
      },
    })
  }

  const handleRevokeAll = () => {
    bsConfirm({
      title: t("openApiManagement.keys.revokeAllConfirmTitle"),
      desc: t("openApiManagement.keys.revokeAllConfirm"),
      okTxt: t("openApiManagement.actions.revokeAll"),
      onOk: (close) => {
        close()
        setLoading(true)
        void captureAndAlertRequestErrorHoc(
          revokeAllServiceAccountKeysApi(serviceAccountId),
        )
          .then(async (result) => {
            if (!result) return
            const { revoked } = result
            toast({
              title: t("openApiManagement.keys.revokeAllConfirmTitle"),
              description: t("openApiManagement.feedback.keysRevoked", {
                count: revoked,
              }),
              variant: "success",
            })
            await loadKeys()
            onKeysChanged?.()
          })
          .finally(() => setLoading(false))
      },
    })
  }

  const scopeLabelKeys = new Map(
    scopes.map((scope) => [scope.code, scope.label_key]),
  )

  const renderScopes = (key: ApiKeyItem) => {
    if (!key.scopes.length) {
      return (
        <span className="text-muted-foreground">
          {t("openApiManagement.keys.noPermissions")}
        </span>
      )
    }
    return (
      <div className="flex flex-wrap gap-1">
        {key.scopes.map((code) => (
          <span key={code} className="rounded bg-muted px-1.5 py-0.5 text-xs">
            {t(
              scopeLabelKeys.get(code) ||
                `openApiManagement.scopes.${code.replace(":", "_")}.label`,
            )}
          </span>
        ))}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-end gap-2">
        <Button
          variant="outline"
          disabled={loading || loadingData || !keys.some((key) => key.is_valid)}
          onClick={handleRevokeAll}
        >
          {t("openApiManagement.actions.revokeAll")}
        </Button>
        <Button
          disabled={
            loading ||
            loadingData ||
            loadingScopes ||
            !scopes.length ||
            !accountEnabled
          }
          onClick={() => {
            setEditingKey(null)
            setDialogOpen(true)
          }}
        >
          {t("openApiManagement.keys.issue")}
        </Button>
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
            const statusKey = key.is_valid
              ? "active"
              : key.revoked_at
                ? "revoked"
                : "expired"
            return (
              <TableRow key={key.id}>
                <TableCell>{key.name}</TableCell>
                <TableCell>
                  <code>{key.key_mask}</code>
                </TableCell>
                <TableCell className="max-w-72">{renderScopes(key)}</TableCell>
                <TableCell>
                  {key.delegate_scopes
                    .map((scope) => {
                      const name =
                        scope.subject_name ||
                        `${scope.subject_type}:${scope.subject_id}`
                      return scope.subject_type === "department"
                        ? t(
                            "openApiManagement.serviceAccount.departmentScope",
                            { name },
                          )
                        : name
                    })
                    .join(", ") || "-"}
                </TableCell>
                <TableCell>
                  {key.last_used_at
                    ? formatIsoDateTime(key.last_used_at)
                    : t("openApiManagement.serviceAccount.neverUsed")}
                </TableCell>
                <TableCell>
                  {key.expires_at
                    ? formatIsoDateTime(key.expires_at)
                    : t("openApiManagement.keys.neverExpires")}
                </TableCell>
                <TableCell>
                  <Badge variant={key.is_valid ? "outline" : "secondary"}>
                    {t(`openApiManagement.status.${statusKey}`)}
                  </Badge>
                </TableCell>
                <TableCell className="text-right">
                  <Button
                    variant="link"
                    disabled={
                      loading ||
                      loadingScopes ||
                      !scopes.length ||
                      !key.is_valid
                    }
                    onClick={() => {
                      setEditingKey(key)
                      setDialogOpen(true)
                    }}
                  >
                    {t("edit")}
                  </Button>
                  <Button
                    variant="link"
                    disabled={loading || !key.is_valid}
                    onClick={() => handleRevoke(key.id)}
                  >
                    {t("openApiManagement.actions.revoke")}
                  </Button>
                </TableCell>
              </TableRow>
            )
          })}
          {loadingData ? (
            <TableRow>
              <TableCell colSpan={8} className="py-8 text-center">
                <Loader2
                  aria-label={t("loading")}
                  className="mx-auto size-5 animate-spin"
                />
              </TableCell>
            </TableRow>
          ) : null}
          {!loadingData && !keys.length ? (
            <TableRow>
              <TableCell
                colSpan={8}
                className="text-center text-muted-foreground"
              >
                {t("openApiManagement.empty")}
              </TableCell>
            </TableRow>
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
        onIssued={(issued) => {
          setDialogOpen(false)
          setEditingKey(null)
          setIssuedKey(issued)
          void loadKeys()
          onKeysChanged?.()
        }}
        onUpdated={() => {
          setDialogOpen(false)
          setEditingKey(null)
          void loadKeys()
          onKeysChanged?.()
        }}
      />
      <KeyRevealDialog
        plaintext={issuedKey?.plaintext || null}
        onClose={() => setIssuedKey(null)}
      />
    </div>
  )
}
