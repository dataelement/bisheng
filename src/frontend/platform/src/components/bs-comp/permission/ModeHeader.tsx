import { Button } from "@/components/bs-ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/bs-ui/dialog"
import {
  applyResourcePermissionModeDraftApi,
  createResourcePermissionModeDraftApi,
  type ApplyPermissionModeDraftResult,
  type PermissionModeDraft,
  type ResourcePermissionContext,
  type ResourcePermissionMode,
} from "@/controllers/API/permission"
import { AlertTriangle, GitBranch, Loader2 } from "lucide-react"
import { useState } from "react"
import { useTranslation } from "react-i18next"
import type { ResourceType } from "./types"

interface ModeHeaderProps {
  resourceType: ResourceType
  resourceId: string
  context: ResourcePermissionContext
  onApplied: (result: ApplyPermissionModeDraftResult) => void
  now?: Date
}

function createModeIdempotencyKey(): string {
  return `mode-apply-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

export function ModeHeader({
  resourceType,
  resourceId,
  context,
  onApplied,
  now = new Date(),
}: ModeHeaderProps) {
  const { t } = useTranslation("permission")
  const [draft, setDraft] = useState<PermissionModeDraft | null>(null)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [previewing, setPreviewing] = useState(false)
  const [applying, setApplying] = useState(false)
  const [conflict, setConflict] = useState(false)
  const targetMode: ResourcePermissionMode =
    context.mode === "CUSTOM" ? "INHERIT" : "CUSTOM"
  const parent =
    context.parent_type && context.parent_id
      ? `${context.parent_type}:${context.parent_id}`
      : null
  const expired =
    draft !== null && new Date(draft.expires_at).getTime() <= now.getTime()
  const canSwitch =
    context.can_manage_permission && parent !== null && !previewing && !applying

  const handlePreview = async () => {
    if (!canSwitch) return
    setPreviewing(true)
    setConflict(false)
    try {
      const result = await createResourcePermissionModeDraftApi(
        resourceType,
        resourceId,
        {
          target_mode: targetMode,
          expected_resource_version: context.resource_version,
          expected_catalog_release_id: context.catalog_release_id,
        },
      )
      setDraft(result)
      setConfirmOpen(true)
    } catch {
      setConflict(true)
    } finally {
      setPreviewing(false)
    }
  }

  const handleApply = async () => {
    if (!draft || expired || applying) return
    setApplying(true)
    setConflict(false)
    try {
      const result = await applyResourcePermissionModeDraftApi(
        resourceType,
        resourceId,
        draft.draft_id,
        {
          idempotency_key: createModeIdempotencyKey(),
          expected_resource_version: context.resource_version,
          expected_catalog_release_id: context.catalog_release_id,
          confirmed: true,
        },
      )
      onApplied(result)
      setConfirmOpen(false)
      setDraft(null)
    } catch {
      setConflict(true)
    } finally {
      setApplying(false)
    }
  }

  return (
    <>
      <section className="rounded-xl border bg-muted/20 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-full bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary">
                {t(`mode.${context.mode.toLowerCase()}`)}
              </span>
              <span className="text-xs text-muted-foreground">
                {t("mode.projection")}: {context.projection_state}
              </span>
            </div>
            {parent && (
              <p className="mt-2 flex items-center gap-1 text-xs text-muted-foreground">
                <GitBranch aria-hidden="true" className="size-3" />
                {t("mode.parent")}: <span>{parent}</span>
              </p>
            )}
          </div>
          {context.can_manage_permission && parent && (
            <Button
              type="button"
              variant="outline"
              className="min-h-11"
              aria-label={t(
                targetMode === "INHERIT"
                  ? "mode.switchToInherit"
                  : "mode.switchToCustom",
              )}
              disabled={!canSwitch}
              onClick={() => void handlePreview()}
            >
              {previewing && (
                <Loader2
                  aria-hidden="true"
                  className="mr-2 size-4 animate-spin"
                />
              )}
              {t(
                targetMode === "INHERIT"
                  ? "mode.switchToInherit"
                  : "mode.switchToCustom",
              )}
            </Button>
          )}
        </div>
        {conflict && !confirmOpen && (
          <p
            className="mt-3 flex items-center gap-2 text-sm font-medium text-red-700"
            role="alert"
          >
            <AlertTriangle aria-hidden="true" className="size-4" />
            {t("mode.conflict")}
          </p>
        )}
      </section>

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("mode.confirmTitle")}</DialogTitle>
            <DialogDescription>
              {t("mode.confirmDescription")}
            </DialogDescription>
          </DialogHeader>
          {draft && (
            <div className="space-y-3">
              <div className="rounded-lg border bg-muted/30 p-3">
                <p className="text-xs text-muted-foreground">
                  {t("mode.affectedAssignees")}
                </p>
                <p
                  data-testid="mode-affected-assignees"
                  className="mt-1 text-xl font-semibold tabular-nums"
                >
                  {draft.affected_assignees}
                </p>
              </div>
              {expired && (
                <p
                  className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm font-medium text-amber-900"
                  role="alert"
                >
                  {t("mode.expired")}
                </p>
              )}
              {conflict && (
                <p className="text-sm font-medium text-red-700" role="alert">
                  {t("mode.conflict")}
                </p>
              )}
            </div>
          )}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              className="min-h-11"
              disabled={applying}
              onClick={() => setConfirmOpen(false)}
            >
              {t("mode.cancel")}
            </Button>
            <Button
              type="button"
              className="min-h-11"
              disabled={!draft || expired || applying}
              onClick={() => void handleApply()}
            >
              {applying ? t("mode.applying") : t("mode.confirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
