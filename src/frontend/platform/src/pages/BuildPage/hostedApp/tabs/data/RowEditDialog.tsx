/**
 * Single-row edit dialog (AC-56).
 *
 * One row, the editable columns only — the key column and binary columns are
 * shown read-only so the owner can see what they are editing without being
 * able to break the address of the row. Saving asks for confirmation first:
 * the write lands in the application's live database with no undo, and the
 * backend audits it as `app.data_row_edit`.
 *
 * Only changed columns are sent. An empty input is an empty string; NULL is a
 * separate, explicit choice per nullable column, because the two are different
 * values to the application and a form that conflates them silently rewrites
 * every empty string it touches.
 */
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
import { Button } from "@/components/bs-ui/button"
import { Checkbox } from "@/components/bs-ui/checkBox"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/bs-ui/dialog"
import { Input } from "@/components/bs-ui/input"
import {
  getHostedAppErrorCode,
  getHostedAppErrorMessage,
  HOSTED_APP_ERROR,
} from "@/controllers/API/hostedApp"
import {
  updateHostedAppRowApi,
  type HostedAppRow,
  type HostedAppTableSchema,
} from "@/controllers/API/hostedAppData"
import { useEffect, useMemo, useState } from "react"
import { useTranslation } from "react-i18next"
import {
  buildRowPatch,
  draftFromRow,
  editableColumns,
  formatCell,
  type CellDraft,
} from "./dataTabModel"

interface RowEditDialogProps {
  appId: string
  schema: HostedAppTableSchema
  /** `null` closes the dialog. */
  row: HostedAppRow | null
  onClose: () => void
  /** Called after a successful save so the grid re-reads the page. */
  onSaved: () => void
}

export function RowEditDialog({ appId, schema, row, onClose, onSaved }: RowEditDialogProps) {
  const { t } = useTranslation()
  const columns = useMemo(() => editableColumns(schema), [schema])
  const [draft, setDraft] = useState<Record<string, CellDraft>>({})
  const [saving, setSaving] = useState(false)
  const [failure, setFailure] = useState("")

  useEffect(() => {
    if (!row) return
    setDraft(draftFromRow(columns, row.values))
    setFailure("")
  }, [row, columns])

  const patch = useMemo(
    () => (row ? buildRowPatch(columns, row.values, draft) : {}),
    [columns, row, draft],
  )
  const changedCount = Object.keys(patch).length

  const handleText = (name: string, text: string) => {
    setDraft((prev) => ({ ...prev, [name]: { text, setNull: false } }))
  }

  const handleNull = (name: string, setNull: boolean) => {
    setDraft((prev) => ({ ...prev, [name]: { text: prev[name]?.text ?? "", setNull } }))
  }

  const runSave = async () => {
    if (!row) return
    setSaving(true)
    setFailure("")
    try {
      await updateHostedAppRowApi(appId, schema.table, row.key, patch)
      onSaved()
      onClose()
    } catch (error) {
      const code = getHostedAppErrorCode(error)
      if (code === HOSTED_APP_ERROR.DATA_ROW_NOT_FOUND) {
        setFailure(t("hostedApp.data.rowMoved"))
      } else if (code === HOSTED_APP_ERROR.DATA_BUSY) {
        setFailure(t("hostedApp.data.busy"))
      } else {
        setFailure(getHostedAppErrorMessage(error) || t("hostedApp.data.saveFailed"))
      }
    } finally {
      setSaving(false)
    }
  }

  const handleSave = () => {
    if (!row || saving || changedCount === 0) return
    bsConfirm({
      title: t("hostedApp.data.confirmTitle"),
      desc: t("hostedApp.data.confirmDesc", {
        table: schema.table,
        key: formatCell(row.key),
        count: changedCount,
      }),
      okTxt: t("hostedApp.data.save"),
      onOk(next: () => void) {
        next()
        void runSave()
      },
    })
  }

  return (
    <Dialog open={!!row} onOpenChange={(open) => !open && !saving && onClose()}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>{t("hostedApp.data.editTitle")}</DialogTitle>
          <DialogDescription>
            {row
              ? t("hostedApp.data.editDesc", {
                  table: schema.table,
                  keyColumn: schema.key.column,
                  key: formatCell(row.key),
                })
              : ""}
          </DialogDescription>
        </DialogHeader>

        {row && (
          <div className="flex max-h-[60vh] flex-col gap-3 overflow-y-auto pr-1">
            {schema.columns.map((column) => {
              const editable = columns.some((c) => c.name === column.name)
              const cell = draft[column.name]
              return (
                <div key={column.name} className="flex flex-col gap-1">
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <span className="font-medium text-foreground">{column.name}</span>
                    {column.type && <span>{column.type}</span>}
                    {column.name === schema.key.column && (
                      <span className="rounded-sm bg-muted px-1">{t("hostedApp.data.keyBadge")}</span>
                    )}
                    {!column.editable && (
                      <span className="rounded-sm bg-muted px-1">{t("hostedApp.data.binaryBadge")}</span>
                    )}
                  </div>
                  {editable && cell ? (
                    <div className="flex items-center gap-3">
                      <Input
                        aria-label={column.name}
                        value={cell.text}
                        disabled={cell.setNull || saving}
                        onChange={(event) => handleText(column.name, event.target.value)}
                      />
                      {!column.notnull && (
                        <label className="flex shrink-0 items-center gap-1 text-xs text-muted-foreground">
                          <Checkbox
                            aria-label={t("hostedApp.data.setNull", { column: column.name })}
                            checked={cell.setNull}
                            disabled={saving}
                            onCheckedChange={(checked) => handleNull(column.name, checked === true)}
                          />
                          {t("hostedApp.data.nullLabel")}
                        </label>
                      )}
                    </div>
                  ) : (
                    <p className="truncate rounded-md border bg-muted/40 px-3 py-1.5 text-sm text-muted-foreground">
                      {formatCell(row.values[column.name]) || t("hostedApp.data.nullLabel")}
                    </p>
                  )}
                </div>
              )
            })}
          </div>
        )}

        {!!failure && <p className="text-sm text-destructive">{failure}</p>}

        <DialogFooter className="flex items-center justify-between sm:justify-between">
          <span className="text-xs text-muted-foreground">
            {t("hostedApp.data.changedCount", { count: changedCount })}
          </span>
          <div className="flex gap-2">
            <Button variant="outline" disabled={saving} onClick={onClose}>
              {t("hostedApp.data.cancel")}
            </Button>
            <Button disabled={saving || changedCount === 0} onClick={handleSave}>
              {t("hostedApp.data.save")}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
