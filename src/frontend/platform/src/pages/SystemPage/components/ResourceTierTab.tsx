import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
import { Badge } from "@/components/bs-ui/badge"
import { Button } from "@/components/bs-ui/button"
import { Input, Textarea } from "@/components/bs-ui/input"
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
  listResourceTiersApi,
  type ResourceTierAdminItem,
  type ResourceTierPatch,
  updateResourceTierApi,
} from "@/controllers/API/hostedApp"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { Loader2 } from "lucide-react"
import { useCallback, useEffect, useState } from "react"
import { useTranslation } from "react-i18next"

/**
 * System page "resource tiers" tab (F055 AC-45 / T066).
 *
 * Super admin only and only when the app-factory runtime layer is deployed —
 * both gates live in `SystemPage/index.tsx`, this component assumes them.
 *
 * Three things are deliberate:
 * - **No delete button.** Tiers are retired with "disable"; `app_version.tier_id`
 *   is a frozen reference and a deleted tier would leave old versions unable to
 *   resolve their limits (AC-47). The backend offers no DELETE either.
 * - **Disable is a button plus a confirm, not a switch.** The Switch spec
 *   reserves switches for settings with no consequences beyond themselves;
 *   retiring a tier changes what every publisher may choose.
 * - **Inline edit is plain `useState`.** The platform has no form library, and
 *   the row has three fields.
 */

type TierDraft = {
  name: string
  cpu: string
  memory: string
  description: string
}

function draftOf(row: ResourceTierAdminItem): TierDraft {
  return {
    name: row.name,
    cpu: String(row.cpu_millicores),
    memory: String(row.memory_mb),
    description: row.description ?? "",
  }
}

/** Positive whole number, or `null` when the text is not one. */
function parsePositiveInt(text: string): number | null {
  const trimmed = text.trim()
  if (!/^\d+$/.test(trimmed)) return null
  const value = Number(trimmed)
  return value > 0 ? value : null
}

export function ResourceTierTab() {
  const { t } = useTranslation()
  const [rows, setRows] = useState<ResourceTierAdminItem[]>([])
  const [loading, setLoading] = useState(true)
  /** Code of the row being edited inline; one at a time. */
  const [editingCode, setEditingCode] = useState<string | null>(null)
  const [draft, setDraft] = useState<TierDraft>({ name: "", cpu: "", memory: "", description: "" })
  /** Code of the row whose request is in flight; disables its buttons. */
  const [busyCode, setBusyCode] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const list = await captureAndAlertRequestErrorHoc(listResourceTiersApi())
      if (list) setRows(list)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const applyPatch = (row: ResourceTierAdminItem, patch: ResourceTierPatch, feedbackKey: string) => {
    setBusyCode(row.code)
    void captureAndAlertRequestErrorHoc(updateResourceTierApi(row.code, patch))
      .then((updated) => {
        if (!updated) return
        setRows((current) => current.map((item) => (item.code === updated.code ? updated : item)))
        setEditingCode((current) => (current === row.code ? null : current))
        toast({
          title: t("hostedApp.tierAdmin.title"),
          description: t(feedbackKey),
          variant: "success",
        })
      })
      .finally(() => setBusyCode(null))
  }

  const handleEdit = (row: ResourceTierAdminItem) => {
    setEditingCode(row.code)
    setDraft(draftOf(row))
  }

  const handleCancel = () => {
    setEditingCode(null)
  }

  /** Validate the draft and reduce it to the fields that actually changed. */
  const buildPatch = (row: ResourceTierAdminItem): ResourceTierPatch | null => {
    const name = draft.name.trim()
    if (!name) {
      toast({ title: t("prompt"), description: t("hostedApp.tierAdmin.validation.name"), variant: "error" })
      return null
    }
    const cpu = parsePositiveInt(draft.cpu)
    if (cpu === null) {
      toast({ title: t("prompt"), description: t("hostedApp.tierAdmin.validation.cpu"), variant: "error" })
      return null
    }
    const memory = parsePositiveInt(draft.memory)
    if (memory === null) {
      toast({ title: t("prompt"), description: t("hostedApp.tierAdmin.validation.memory"), variant: "error" })
      return null
    }
    const description = draft.description.trim() || null
    const patch: ResourceTierPatch = {}
    if (name !== row.name) patch.name = name
    if (cpu !== row.cpu_millicores) patch.cpu_millicores = cpu
    if (memory !== row.memory_mb) patch.memory_mb = memory
    if (description !== (row.description ?? null)) patch.description = description
    return patch
  }

  const handleSave = (row: ResourceTierAdminItem) => {
    const patch = buildPatch(row)
    if (patch === null) return
    if (Object.keys(patch).length === 0) {
      setEditingCode(null)
      return
    }
    bsConfirm({
      title: t("hostedApp.tierAdmin.saveConfirmTitle"),
      desc: t("hostedApp.tierAdmin.saveConfirmDesc", { name: row.name, count: row.in_use_app_count }),
      okTxt: t("hostedApp.tierAdmin.actions.save"),
      onOk: (close) => {
        close()
        applyPatch(row, patch, "hostedApp.tierAdmin.feedback.saved")
      },
    })
  }

  const handleToggleEnabled = (row: ResourceTierAdminItem) => {
    const disabling = row.enabled
    bsConfirm({
      title: t(disabling ? "hostedApp.tierAdmin.disableConfirmTitle" : "hostedApp.tierAdmin.enableConfirmTitle"),
      desc: t(disabling ? "hostedApp.tierAdmin.disableConfirmDesc" : "hostedApp.tierAdmin.enableConfirmDesc", {
        name: row.name,
        count: row.in_use_app_count,
      }),
      okTxt: t(disabling ? "hostedApp.tierAdmin.actions.disable" : "hostedApp.tierAdmin.actions.enable"),
      onOk: (close) => {
        close()
        applyPatch(
          row,
          { enabled: !row.enabled },
          disabling ? "hostedApp.tierAdmin.feedback.disabled" : "hostedApp.tierAdmin.feedback.enabled",
        )
      },
    })
  }

  const renderRow = (row: ResourceTierAdminItem) => {
    const editing = editingCode === row.code
    const busy = busyCode === row.code
    return (
      <TableRow key={row.code} data-testid={`tier-row-${row.code}`}>
        <TableCell>
          {editing ? (
            <Input
              aria-label={t("hostedApp.tierAdmin.columns.name")}
              value={draft.name}
              maxLength={64}
              onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))}
            />
          ) : (
            <div className="flex items-center gap-2">
              <span>{row.name}</span>
              {row.is_default && (
                <Badge variant="gray" title={t("hostedApp.tierAdmin.defaultHint")}>
                  {t("hostedApp.tierAdmin.defaultTag")}
                </Badge>
              )}
            </div>
          )}
        </TableCell>
        <TableCell>
          {editing ? (
            <Input
              aria-label={t("hostedApp.tierAdmin.columns.cpu")}
              className="w-28"
              inputMode="numeric"
              value={draft.cpu}
              onChange={(event) => setDraft((current) => ({ ...current, cpu: event.target.value }))}
            />
          ) : (
            row.cpu_millicores
          )}
        </TableCell>
        <TableCell>
          {editing ? (
            <Input
              aria-label={t("hostedApp.tierAdmin.columns.memory")}
              className="w-28"
              inputMode="numeric"
              value={draft.memory}
              onChange={(event) => setDraft((current) => ({ ...current, memory: event.target.value }))}
            />
          ) : (
            row.memory_mb
          )}
        </TableCell>
        <TableCell className="max-w-96">
          {editing ? (
            <Textarea
              aria-label={t("hostedApp.tierAdmin.columns.description")}
              value={draft.description}
              maxLength={500}
              rows={2}
              onChange={(event) => setDraft((current) => ({ ...current, description: event.target.value }))}
            />
          ) : (
            <span className="text-muted-foreground">{row.description || "-"}</span>
          )}
        </TableCell>
        <TableCell>
          <Badge variant={row.enabled ? "outline" : "secondary"}>
            {t(row.enabled ? "hostedApp.tierAdmin.status.enabled" : "hostedApp.tierAdmin.status.disabled")}
          </Badge>
        </TableCell>
        <TableCell>{row.in_use_app_count}</TableCell>
        <TableCell className="text-right">
          {editing ? (
            <>
              <Button variant="link" disabled={busy} onClick={() => handleSave(row)}>
                {busy ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : null}
                {t("hostedApp.tierAdmin.actions.save")}
              </Button>
              <Button variant="link" disabled={busy} onClick={handleCancel}>
                {t("hostedApp.tierAdmin.actions.cancel")}
              </Button>
            </>
          ) : (
            <>
              <Button variant="link" disabled={busy || editingCode !== null} onClick={() => handleEdit(row)}>
                {t("hostedApp.tierAdmin.actions.edit")}
              </Button>
              {/* The default tier is what a manifest without `tier:` resolves to; retiring it is refused server-side (16263), so no button. */}
              {!row.is_default && (
                <Button
                  variant="link"
                  disabled={busy || editingCode !== null}
                  onClick={() => handleToggleEnabled(row)}
                >
                  {t(row.enabled ? "hostedApp.tierAdmin.actions.disable" : "hostedApp.tierAdmin.actions.enable")}
                </Button>
              )}
            </>
          )}
        </TableCell>
      </TableRow>
    )
  }

  return (
    <div className="h-full overflow-y-auto px-2 py-4">
      <p className="mb-4 text-sm text-muted-foreground">{t("hostedApp.tierAdmin.hint")}</p>
      {loading && rows.length === 0 ? (
        <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t("hostedApp.tierAdmin.loading")}
        </div>
      ) : rows.length === 0 ? (
        <p className="py-8 text-center text-sm text-muted-foreground">{t("hostedApp.tierAdmin.empty")}</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("hostedApp.tierAdmin.columns.name")}</TableHead>
              <TableHead>{t("hostedApp.tierAdmin.columns.cpu")}</TableHead>
              <TableHead>{t("hostedApp.tierAdmin.columns.memory")}</TableHead>
              <TableHead>{t("hostedApp.tierAdmin.columns.description")}</TableHead>
              <TableHead>{t("hostedApp.tierAdmin.columns.status")}</TableHead>
              <TableHead>{t("hostedApp.tierAdmin.columns.inUse")}</TableHead>
              <TableHead className="text-right">{t("operations")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>{rows.map(renderRow)}</TableBody>
        </Table>
      )}
    </div>
  )
}
