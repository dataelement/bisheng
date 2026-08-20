import { Button } from "@/components/bs-ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/bs-ui/dialog"
import type {
  PermissionCatalogAction,
  PermissionCatalogActionChange,
  PermissionCatalogDraft,
  PermissionCatalogModel,
  PermissionCatalogModelChange,
  PublishPermissionCatalogDraftRequest,
} from "@/controllers/API/permission"
import { formatDate } from "@/util/utils"
import { AlertTriangle } from "lucide-react"
import { useState } from "react"
import { useTranslation } from "react-i18next"
import { actionLabel } from "./actionLabels"
import { formatBlockerMessage } from "./blockerMessages"

interface ImpactDialogProps {
  open: boolean
  draft: PermissionCatalogDraft | null
  onOpenChange: (open: boolean) => void
  onPublish: (
    draftId: number,
    payload: PublishPermissionCatalogDraftRequest,
  ) => Promise<unknown>
  // Used only to resolve blocker model keys and action codes into the display
  // names an operator recognises; optional so the dialog still renders raw
  // blockers when the catalog is unavailable.
  models?: PermissionCatalogModel[]
  actions?: PermissionCatalogAction[]
  now?: Date
}

// The backend sends UTC ISO-8601 with microseconds; rendering it raw showed
// both an unreadable string and a time 8 hours off for CST operators. The
// impact window is only 10 minutes, so keep seconds.
function formatExpiry(iso: string): string {
  const parsed = new Date(iso)
  if (Number.isNaN(parsed.getTime())) return iso
  return formatDate(parsed, "yyyy-MM-dd HH:mm:ss")
}

function createPublishIdempotencyKey(): string {
  return `catalog-publish-${Date.now()}-${Math.random()
    .toString(36)
    .slice(2, 10)}`
}

export function ImpactDialog({
  open,
  draft,
  onOpenChange,
  onPublish,
  models,
  actions,
  now = new Date(),
}: ImpactDialogProps) {
  const { t } = useTranslation("permission")
  const [publishing, setPublishing] = useState(false)
  const [publishFailed, setPublishFailed] = useState(false)

  if (!draft) return null

  const expired = new Date(draft.impact.expires_at).getTime() <= now.getTime()
  const blocked = draft.impact.blockers.length > 0
  const actionChanges = draft.impact.action_changes ?? []
  const modelChanges = draft.impact.model_changes ?? []

  const levelName = (level: number | null) =>
    level === null
      ? t("actionLevel.unassigned")
      : t("actionLevel.level", { level })

  const displayActionName = (code: string, fallback?: string) =>
    actionLabel(
      t,
      code,
      actions?.find((action) => action.code === code)?.name ?? fallback,
    )

  const displayModelName = (change: PermissionCatalogModelChange) => {
    if (
      change.kind === "STANDARD" &&
      ["viewer", "editor", "manager", "owner"].includes(change.model_key)
    ) {
      return t(`level.${change.model_key}`)
    }
    return change.model_name
  }

  const actionChangeLines = (change: PermissionCatalogActionChange) => {
    const name = displayActionName(change.action_code, change.action_name)
    const lines: string[] = []
    if (change.before_level !== change.after_level) {
      lines.push(
        t("impact.actionLevelChanged", {
          name,
          from: levelName(change.before_level),
          to: levelName(change.after_level),
        }),
      )
    }
    if (change.before_active !== change.after_active) {
      lines.push(
        t(
          change.after_active
            ? "impact.actionEnabled"
            : "impact.actionDisabled",
          { name },
        ),
      )
    }
    if (lines.length === 0) {
      lines.push(t("impact.actionConfigurationChanged", { name }))
    }
    return lines
  }

  const handlePublish = async () => {
    if (publishing || expired || blocked) return
    setPublishing(true)
    setPublishFailed(false)
    try {
      await onPublish(draft.draft_id, {
        expected_current_release_id: draft.base_release_id,
        idempotency_key: createPublishIdempotencyKey(),
        confirmed: true,
      })
      onOpenChange(false)
    } catch {
      setPublishFailed(true)
    } finally {
      setPublishing(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t("impact.title")}</DialogTitle>
          <DialogDescription>{t("impact.description")}</DialogDescription>
        </DialogHeader>

        {actionChanges.length > 0 && (
          <section className="space-y-2" aria-labelledby="impact-change-title">
            <h3 id="impact-change-title" className="text-sm font-semibold">
              {t("impact.changeTitle")}
            </h3>
            <ul className="space-y-1 rounded-lg border bg-muted/20 px-4 py-3 text-sm">
              {actionChanges.flatMap((change) =>
                actionChangeLines(change).map((line, index) => (
                  <li key={`${change.action_code}-${index}`}>{line}</li>
                )),
              )}
            </ul>
          </section>
        )}

        <section
          className="rounded-xl border border-primary/30 bg-primary/5 p-4"
          aria-labelledby="impact-record-title"
        >
          <h3
            id="impact-record-title"
            className="text-sm font-medium text-muted-foreground"
          >
            {t("impact.affectedRecords")}
          </h3>
          <p
            data-testid="impact-assignee-count"
            className="mt-1 text-3xl font-semibold tabular-nums text-foreground"
          >
            {draft.impact.assignee_count}
            <span className="ml-1 text-base font-medium">
              {t("impact.recordUnit")}
            </span>
          </p>
          <p className="mt-1 text-sm text-muted-foreground">
            {draft.impact.assignee_count > 0
              ? t("impact.recordDescription")
              : t("impact.noRecordChanges")}
          </p>
        </section>

        {modelChanges.length > 0 && (
          <section className="space-y-2" aria-labelledby="impact-model-title">
            <h3 id="impact-model-title" className="text-sm font-semibold">
              {t("impact.modelChanges")}
            </h3>
            <div className="space-y-2">
              {modelChanges.map((change) => {
                const levelChanged = change.before_level !== change.after_level
                const actionsChanged =
                  change.added_action_codes.length > 0 ||
                  change.removed_action_codes.length > 0
                return (
                  <article
                    key={change.model_key}
                    className="rounded-lg border px-4 py-3 text-sm"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="font-medium text-foreground">
                        {displayModelName(change)}
                      </p>
                      <span className="text-xs text-muted-foreground">
                        {t(
                          change.kind === "CUSTOM"
                            ? "model.kind.custom"
                            : "model.kind.standard",
                        )}
                      </span>
                    </div>
                    <ul className="mt-2 space-y-1 text-muted-foreground">
                      {change.affected_assignee_count > 0 && (
                        <li>
                          {t("impact.modelAffectedRecords", {
                            count: change.affected_assignee_count,
                          })}
                        </li>
                      )}
                      {change.added_action_codes.length > 0 && (
                        <li className="text-emerald-700">
                          {t("impact.actionsAdded", {
                            actions: change.added_action_codes
                              .map((code) => displayActionName(code))
                              .join(t("impact.actionSeparator")),
                          })}
                        </li>
                      )}
                      {change.removed_action_codes.length > 0 && (
                        <li className="text-red-700">
                          {t("impact.actionsRemoved", {
                            actions: change.removed_action_codes
                              .map((code) => displayActionName(code))
                              .join(t("impact.actionSeparator")),
                          })}
                        </li>
                      )}
                      {levelChanged && (
                        <li>
                          {t("impact.modelLevelChanged", {
                            from: levelName(change.before_level),
                            to: levelName(change.after_level),
                          })}
                        </li>
                      )}
                      {change.kind === "CUSTOM" &&
                        levelChanged &&
                        !actionsChanged && (
                          <li>{t("impact.customLevelOnly")}</li>
                        )}
                      {!levelChanged && !actionsChanged && (
                        <li>{t("impact.modelConfigurationChanged")}</li>
                      )}
                    </ul>
                  </article>
                )
              })}
            </div>
            <p className="text-xs text-muted-foreground">
              {t("impact.unlistedModelsUnchanged")}
            </p>
          </section>
        )}

        {blocked && (
          <div
            className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-900"
            role="alert"
          >
            <div className="flex items-center gap-2 font-medium">
              <AlertTriangle aria-hidden="true" className="size-4" />
              {t("impact.blocked")}
            </div>
            <ul className="mt-2 list-disc space-y-1 pl-5">
              {draft.impact.blockers.map((blocker) => (
                <li key={blocker}>
                  {formatBlockerMessage(t, blocker, { models, actions })}
                </li>
              ))}
            </ul>
          </div>
        )}

        {expired && (
          <p
            className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm font-medium text-amber-900"
            role="alert"
          >
            {t("impact.expired")}
          </p>
        )}

        {publishFailed && (
          <p className="text-sm font-medium text-red-700" role="alert">
            {t("impact.publishFailed")}
          </p>
        )}

        <p className="text-xs text-muted-foreground">
          {t("impact.expiresAt", { value: formatExpiry(draft.impact.expires_at) })}
        </p>

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            
            disabled={publishing}
            onClick={() => onOpenChange(false)}
          >
            {t("impact.cancel")}
          </Button>
          <Button
            type="button"
            
            disabled={publishing || expired || blocked}
            onClick={() => void handlePublish()}
          >
            {publishing ? t("impact.publishing") : t("impact.publish")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
