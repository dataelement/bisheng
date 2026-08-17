import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
import { Button } from "@/components/bs-ui/button"
import {
  Table,
  TableBody,
  TableCell,
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/bs-ui/table"
import { toast } from "@/components/bs-ui/toast/use-toast"
import { locationContext } from "@/contexts/locationContext"
import {
  getOpenApiScopesApi,
  getServiceAccountKeysApi,
  revokeAllKeysApi,
  revokeKeyApi,
} from "@/controllers/API/serviceAccount"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { ApiKeyItem, KeyIssuedResponse } from "@/types/api/serviceAccount"
import { formatIsoDateTime } from "@/util/utils"
import { useCallback, useContext, useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { KeyIssueDialog } from "./KeyIssueDialog"
import { KeyRevealDialog } from "./KeyRevealDialog"

interface ApiKeysTabProps {
  serviceAccountId: number
  /** A disabled account cannot be given new keys */
  accountEnabled: boolean
  /** Open the issue dialog on the first frame (right after account creation) */
  autoOpenIssue: boolean
  /** Key changes move the account's valid-key count, so the detail reloads */
  onKeysChanged: () => void
}

const COLUMN_COUNT = 7

type KeyState = "valid" | "revoked" | "expired"

/**
 * A key row carries no status column — validity is derived (backend K3):
 * revoked wins over expired, and `is_valid` already folds in the expiry.
 */
function deriveKeyState(key: ApiKeyItem): KeyState {
  if (key.revoked_at) return "revoked"
  if (!key.is_valid) return "expired"
  return "valid"
}

export function ApiKeysTab({
  serviceAccountId,
  accountEnabled,
  autoOpenIssue,
  onKeysChanged,
}: ApiKeysTabProps) {
  const { t } = useTranslation("serviceAccount")
  const { appConfig } = useContext(locationContext)
  const [keys, setKeys] = useState<ApiKeyItem[]>([])
  const [loading, setLoading] = useState(true)
  const [scopeLabels, setScopeLabels] = useState<Record<string, string>>({})
  const [issueOpen, setIssueOpen] = useState(autoOpenIssue)
  const [editingKey, setEditingKey] = useState<ApiKeyItem | null>(null)
  const [plaintext, setPlaintext] = useState<string | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    captureAndAlertRequestErrorHoc(getServiceAccountKeysApi(serviceAccountId)).then((res) => {
      setLoading(false)
      if (!res) return
      setKeys(res)
    })
  }, [serviceAccountId])

  useEffect(() => {
    load()
  }, [load])

  // Code → localized label for the scope column; unknown codes (e.g. a toolkit
  // bit issued while the open capability layer was deployed, now switched off)
  // fall back to the raw code rather than disappearing.
  useEffect(() => {
    getOpenApiScopesApi()
      .then((res) => {
        const map: Record<string, string> = {}
        for (const scope of res.scopes || []) map[scope.code] = scope.label_key
        setScopeLabels(map)
      })
      .catch(() => setScopeLabels({}))
  }, [])

  const afterMutation = () => {
    load()
    onKeysChanged()
  }

  const handleRevoke = (key: ApiKeyItem) => {
    bsConfirm({
      title: t("keys.revokeConfirmTitle"),
      desc: (
        <div className="space-y-2 text-left">
          <p>{t("keys.revokeConfirmDesc")}</p>
          {appConfig.openPlatformEnabled && <p>{t("keys.revokeConfirmOpenPlatformDesc")}</p>}
        </div>
      ),
      okTxt: t("keys.revoke"),
      onOk(next) {
        captureAndAlertRequestErrorHoc(revokeKeyApi(serviceAccountId, key.id)).then((res) => {
          if (!res) return
          toast({ title: t("title"), description: t("keys.revokeSuccess"), variant: "success" })
          afterMutation()
        })
        next()
      },
    })
  }

  const handleRevokeAll = () => {
    bsConfirm({
      title: t("keys.revokeAllConfirmTitle"),
      desc: (
        <div className="space-y-2 text-left">
          <p>{t("keys.revokeAllConfirmDesc")}</p>
          {appConfig.openPlatformEnabled && <p>{t("keys.revokeConfirmOpenPlatformDesc")}</p>}
        </div>
      ),
      okTxt: t("keys.revokeAll"),
      onOk(next) {
        captureAndAlertRequestErrorHoc(revokeAllKeysApi(serviceAccountId)).then((res) => {
          if (!res) return
          toast({
            title: t("title"),
            description: t("keys.revokeAllSuccess", { count: res.revoked }),
            variant: "success",
          })
          afterMutation()
        })
        next()
      },
    })
  }

  const handleIssued = (issued: KeyIssuedResponse) => {
    setIssueOpen(false)
    setEditingKey(null)
    // The plaintext lives only in this state until the reveal dialog closes.
    setPlaintext(issued.plaintext)
    afterMutation()
  }

  const renderScopes = (key: ApiKeyItem) => {
    if (!key.scopes.length) return <span className="text-gray-400">{t("keys.noScopes")}</span>
    return (
      <div className="flex flex-wrap gap-1">
        {key.scopes.map((code) => (
          <span key={code} className="rounded bg-muted px-1.5 py-0.5 text-xs">
            {scopeLabels[code] ? t(scopeLabels[code]) : code}
          </span>
        ))}
      </div>
    )
  }

  return (
    <div className="space-y-3 py-3">
      <div className="flex justify-end gap-3">
        <Button variant="outline" onClick={handleRevokeAll}>
          {t("keys.revokeAll")}
        </Button>
        <Button
          disabled={!accountEnabled}
          onClick={() => {
            setEditingKey(null)
            setIssueOpen(true)
          }}
        >
          {t("keys.issue")}
        </Button>
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t("keys.columns.name")}</TableHead>
            <TableHead>{t("keys.columns.mask")}</TableHead>
            <TableHead>{t("keys.columns.scopes")}</TableHead>
            <TableHead>{t("keys.columns.lastUsedAt")}</TableHead>
            <TableHead>{t("keys.columns.expiresAt")}</TableHead>
            <TableHead>{t("common.status")}</TableHead>
            <TableHead className="text-right">{t("common.operations")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {keys.map((key) => {
            const state = deriveKeyState(key)
            return (
              <TableRow key={key.id}>
                <TableCell className="max-w-[180px] truncate font-medium">{key.name}</TableCell>
                <TableCell className="font-mono text-xs">{key.key_mask}</TableCell>
                <TableCell className="max-w-[280px]">{renderScopes(key)}</TableCell>
                <TableCell>
                  {key.last_used_at ? (
                    formatIsoDateTime(key.last_used_at)
                  ) : (
                    <span className="text-gray-400">{t("keys.neverUsed")}</span>
                  )}
                </TableCell>
                <TableCell>
                  {key.expires_at ? (
                    formatIsoDateTime(key.expires_at)
                  ) : (
                    <span className="text-gray-400">{t("keys.neverExpires")}</span>
                  )}
                </TableCell>
                <TableCell className={state === "valid" ? "" : "text-gray-400"}>
                  {t(`keys.state.${state}`)}
                </TableCell>
                <TableCell className="whitespace-nowrap text-right">
                  <Button
                    variant="link"
                    className="px-0"
                    disabled={state !== "valid"}
                    onClick={() => {
                      setEditingKey(key)
                      setIssueOpen(true)
                    }}
                  >
                    {t("common.edit")}
                  </Button>
                  <Button
                    variant="link"
                    className="px-0 pl-4 text-red-500"
                    disabled={state !== "valid"}
                    onClick={() => handleRevoke(key)}
                  >
                    {t("keys.revoke")}
                  </Button>
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
        <TableFooter>
          {!loading && !keys.length && (
            <TableRow>
              <TableCell colSpan={COLUMN_COUNT} className="text-center text-gray-400">
                {t("keys.empty")}
              </TableCell>
            </TableRow>
          )}
        </TableFooter>
      </Table>

      <KeyIssueDialog
        open={issueOpen}
        serviceAccountId={serviceAccountId}
        editing={editingKey}
        onClose={() => {
          setIssueOpen(false)
          setEditingKey(null)
        }}
        onIssued={handleIssued}
        onUpdated={() => {
          setIssueOpen(false)
          setEditingKey(null)
          afterMutation()
        }}
      />
      <KeyRevealDialog plaintext={plaintext} onClose={() => setPlaintext(null)} />
    </div>
  )
}
