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
import { AlertTriangle, Loader2, ShieldCheck } from "lucide-react"
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

const MODES: ResourcePermissionMode[] = ["INHERIT", "CUSTOM"]

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
  const hasParent = Boolean(context.parent_type && context.parent_id)
  const expired =
    draft !== null && new Date(draft.expires_at).getTime() <= now.getTime()
  const canSwitch =
    hasParent && context.can_manage_permission && !previewing && !applying

  if (!hasParent) return null

  const handlePreview = async (targetMode: ResourcePermissionMode) => {
    if (!canSwitch || targetMode === context.mode) return
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
      <section
        className="border-y border-[#EBECF0] bg-[#F7F8FA] px-5 py-3"
        data-testid="permission-mode-switch"
      >
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <span className="text-sm font-medium text-[#212121]">
            {t("mode.label")}
          </span>
          <div
            className="inline-flex rounded-[6px] border border-[#D9DDE7] bg-white p-[2px]"
            role="group"
            aria-label={t("mode.label")}
          >
            {MODES.map((mode) => {
              const active = context.mode === mode
              const key = mode.toLowerCase()
              return (
                <button
                  key={mode}
                  type="button"
                  aria-pressed={active}
                  aria-label={
                    active
                      ? t(`mode.${key}`)
                      : t(
                          mode === "INHERIT"
                            ? "mode.switchToInherit"
                            : "mode.switchToCustom",
                        )
                  }
                  disabled={!active && !canSwitch}
                  className="min-h-8 rounded-[4px] px-3 text-sm text-[#4E5969] transition-colors hover:bg-[#F2F3F5] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 disabled:cursor-not-allowed disabled:opacity-50 aria-pressed:bg-primary/10 aria-pressed:font-medium aria-pressed:text-primary aria-pressed:hover:bg-primary/10"
                  onClick={() => void handlePreview(mode)}
                >
                  {previewing && !active && draft?.target_mode !== mode ? (
                    <Loader2
                      aria-hidden="true"
                      className="mr-1 inline size-3.5 animate-spin"
                    />
                  ) : null}
                  {t(`mode.${key}`)}
                </button>
              )
            })}
          </div>
          <p className="flex min-w-0 items-center gap-1.5 text-sm text-[#4E5969]">
            <ShieldCheck aria-hidden="true" className="size-4 shrink-0" />
            {t(
              context.mode === "INHERIT"
                ? "mode.inheritDescription"
                : "mode.customDescription",
            )}
          </p>
        </div>
        <p className="mt-2 pl-0 text-xs leading-5 text-[#86909C] sm:pl-[88px]">
          {t(
            context.mode === "INHERIT"
              ? "mode.inheritHelper"
              : "mode.customHelper",
          )}
        </p>
        {conflict && !confirmOpen && (
          <p
            className="mt-2 flex items-center gap-2 text-sm font-medium text-red-700"
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
