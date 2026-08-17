import { Button } from "@/components/bs-ui/button"
import { DatePicker } from "@/components/bs-ui/calendar/datePicker"
import { Checkbox } from "@/components/bs-ui/checkBox"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/bs-ui/dialog"
import { Input } from "@/components/bs-ui/input"
import { Label } from "@/components/bs-ui/label"
import { toast } from "@/components/bs-ui/toast/use-toast"
import { QuestionTooltip } from "@/components/bs-ui/tooltip"
import { getOpenApiScopesApi, issueKeyApi, updateKeyApi } from "@/controllers/API/serviceAccount"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import {
  ApiKeyItem,
  KeyIssuedResponse,
  KeyUpdateForm,
  OpenApiScope,
} from "@/types/api/serviceAccount"
import { formatDate } from "@/util/utils"
import { useEffect, useMemo, useState } from "react"
import { useTranslation } from "react-i18next"

interface KeyIssueDialogProps {
  open: boolean
  serviceAccountId: number
  /** null = issue a new key; an item = edit that key */
  editing: ApiKeyItem | null
  onClose: () => void
  /** Issue only — hands the plaintext to the one-shot reveal dialog */
  onIssued: (issued: KeyIssuedResponse) => void
  onUpdated: () => void
}

const TOOLKIT_GROUP = "local_dev_toolkit"

/**
 * Backend datetimes are naive server-local, so the expiry is sent without a
 * timezone: an ISO string with a `Z` would arrive tz-aware and blow up the
 * `expires_at > now` comparison.
 */
function toBackendDateTime(date: Date): string {
  return formatDate(date, "yyyy-MM-ddTHH:mm:ss")
}

function sameScopeSet(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false
  const set = new Set(a)
  return b.every((code) => set.has(code))
}

/**
 * Issue / edit form (AC-06 / AC-13 / AC-14 / AC-44).
 *
 * Scopes come from `GET /scopes`, which already reflects this deployment: the
 * three `local_dev_toolkit` bits are absent where the open capability layer is
 * not deployed, so the form can never offer a bit the backend would reject.
 * There is no `delegate` bit and no delegation section — that ships with F050.
 */
export function KeyIssueDialog({
  open,
  serviceAccountId,
  editing,
  onClose,
  onIssued,
  onUpdated,
}: KeyIssueDialogProps) {
  const { t } = useTranslation("serviceAccount")
  const [scopes, setScopes] = useState<OpenApiScope[]>([])
  const [name, setName] = useState("")
  const [expiresAt, setExpiresAt] = useState<string | null>(null)
  const [checked, setChecked] = useState<string[]>([])
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (!open) return
    getOpenApiScopesApi()
      .then((res) => setScopes(res.scopes || []))
      .catch(() => setScopes([]))
  }, [open])

  // Reset / prefill whenever the dialog opens, so a reopened form never shows
  // the previous key's configuration.
  useEffect(() => {
    if (!open) return
    setName(editing?.name || "")
    setExpiresAt(editing?.expires_at || null)
    // Default: nothing checked (AC-06).
    setChecked(editing ? [...editing.scopes] : [])
  }, [open, editing])

  const grouped = useMemo(() => {
    const order: string[] = []
    const byGroup = new Map<string, OpenApiScope[]>()
    for (const scope of scopes) {
      if (!byGroup.has(scope.group)) {
        byGroup.set(scope.group, [])
        order.push(scope.group)
      }
      byGroup.get(scope.group)?.push(scope)
    }
    return order.map((group) => ({ group, items: byGroup.get(group) || [] }))
  }, [scopes])

  // Non-blocking nudge shown as soon as any open-API endpoint bit is picked.
  const showSoftHint = useMemo(() => {
    if (!checked.length) return false
    return scopes.some((s) => checked.includes(s.code) && s.group !== TOOLKIT_GROUP)
  }, [checked, scopes])

  const toggleScope = (code: string, next: boolean) => {
    setChecked((prev) => (next ? [...prev, code] : prev.filter((c) => c !== code)))
  }

  const handleSubmit = () => {
    const trimmed = name.trim()
    if (!trimmed) {
      toast({
        title: t("issueDialog.createTitle"),
        description: t("issueDialog.nameRequired"),
        variant: "error",
      })
      return
    }
    setSubmitting(true)
    if (editing) {
      // PATCH carries changed fields only; `expires_at: null` is an explicit
      // clear, `scopes: []` an explicit "no bits at all".
      const payload: KeyUpdateForm = {}
      if (trimmed !== editing.name) payload.name = trimmed
      if (!sameScopeSet(checked, editing.scopes)) payload.scopes = checked
      if ((expiresAt || null) !== (editing.expires_at || null)) payload.expires_at = expiresAt
      if (!Object.keys(payload).length) {
        setSubmitting(false)
        onClose()
        return
      }
      captureAndAlertRequestErrorHoc(updateKeyApi(serviceAccountId, editing.id, payload)).then(
        (res) => {
          setSubmitting(false)
          if (!res) return
          toast({
            title: t("issueDialog.editTitle"),
            description: t("issueDialog.updateSuccess"),
            variant: "success",
          })
          onUpdated()
        }
      )
      return
    }
    captureAndAlertRequestErrorHoc(
      issueKeyApi(serviceAccountId, {
        name: trimmed,
        scopes: checked,
        expires_at: expiresAt,
      })
    ).then((res) => {
      setSubmitting(false)
      if (!res) return
      onIssued(res)
    })
  }

  const renderScope = (scope: OpenApiScope) => {
    const endpointText = scope.pending_note_key
      ? t(scope.pending_note_key)
      : scope.endpoints.length
        ? `${t("issueDialog.endpointsTitle")}\n${scope.endpoints
            .map((e) => `${e.method} ${e.path}`)
            .join("\n")}`
        : ""
    return (
      <div key={scope.code} className="space-y-1">
        <label className="flex cursor-pointer items-start gap-2">
          <Checkbox
            className="mt-0.5"
            checked={checked.includes(scope.code)}
            onCheckedChange={(v) => toggleScope(scope.code, v === true)}
          />
          <div className="space-y-0.5">
            <div className="flex items-center gap-1 text-sm font-medium">
              {t(scope.label_key)}
              {endpointText && (
                <QuestionTooltip
                  content={<span className="whitespace-pre-line">{endpointText}</span>}
                />
              )}
            </div>
            <p className="text-xs text-muted-foreground">{t(scope.desc_key)}</p>
            {scope.pending_note_key && (
              <p className="text-xs text-muted-foreground">{t(scope.pending_note_key)}</p>
            )}
            {/* Always-visible warnings (identity:read full-org read, app:manage deploy). */}
            {scope.hint_keys.map((key) => (
              <p key={key} className="text-xs font-medium text-orange-500">
                {t(key)}
              </p>
            ))}
          </div>
        </label>
      </div>
    )
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !next && !submitting && onClose()}>
      <DialogContent className="sm:max-w-[640px]">
        <DialogHeader>
          <DialogTitle>
            {editing ? t("issueDialog.editTitle") : t("issueDialog.createTitle")}
          </DialogTitle>
        </DialogHeader>
        <div className="max-h-[60vh] space-y-4 overflow-y-auto py-2 pr-1">
          <div className="space-y-2">
            <Label>{t("common.name")} *</Label>
            <Input
              value={name}
              maxLength={128}
              placeholder={t("issueDialog.namePlaceholder")}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label>{t("issueDialog.expiresAt")}</Label>
            <div className="flex items-center gap-2">
              <DatePicker
                showTime
                value={expiresAt || undefined}
                placeholder={t("issueDialog.expiresAtPlaceholder")}
                onChange={(date) => setExpiresAt(date ? toBackendDateTime(date) : null)}
              />
              {expiresAt && (
                <Button variant="link" className="px-0" onClick={() => setExpiresAt(null)}>
                  {t("issueDialog.clearExpiry")}
                </Button>
              )}
            </div>
          </div>
          <div className="space-y-3">
            <Label>{t("issueDialog.scopes")}</Label>
            <p className="text-xs text-muted-foreground">{t("issueDialog.scopesDefaultHint")}</p>
            {grouped.map(({ group, items }) => (
              <div key={group} className="space-y-2 rounded-md border p-3">
                <p className="text-sm font-medium">{t(`groups.${group}`)}</p>
                <div className="space-y-3">{items.map(renderScope)}</div>
              </div>
            ))}
            {showSoftHint && (
              <p className="text-xs text-orange-500">{t("issueDialog.openApiSoftHint")}</p>
            )}
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" disabled={submitting} onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button disabled={submitting} onClick={handleSubmit}>
            {editing ? t("common.save") : t("issueDialog.submit")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
