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
  PermissionCatalogDraft,
  PublishPermissionCatalogDraftRequest,
} from "@/controllers/API/permission"
import { formatDate } from "@/util/utils"
import { AlertTriangle } from "lucide-react"
import { useState } from "react"
import { useTranslation } from "react-i18next"

interface ImpactDialogProps {
  open: boolean
  draft: PermissionCatalogDraft | null
  onOpenChange: (open: boolean) => void
  onPublish: (
    draftId: number,
    payload: PublishPermissionCatalogDraftRequest,
  ) => Promise<unknown>
  now?: Date
}

interface ImpactMetricProps {
  label: string
  value: number
  testId: string
}

function ImpactMetric({ label, value, testId }: ImpactMetricProps) {
  return (
    <div className="rounded-lg border bg-muted/30 p-3">
      <dt className="text-xs font-medium text-muted-foreground">{label}</dt>
      <dd
        data-testid={testId}
        className="mt-1 text-xl font-semibold tabular-nums text-foreground"
      >
        {value}
      </dd>
    </div>
  )
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
  now = new Date(),
}: ImpactDialogProps) {
  const { t } = useTranslation("permission")
  const [publishing, setPublishing] = useState(false)
  const [publishFailed, setPublishFailed] = useState(false)

  if (!draft) return null

  const expired = new Date(draft.impact.expires_at).getTime() <= now.getTime()
  const blocked = draft.impact.blockers.length > 0

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

        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <ImpactMetric
            label={t("impact.resources")}
            value={draft.impact.resource_count}
            testId="impact-resource-count"
          />
          <ImpactMetric
            label={t("impact.grants")}
            value={draft.impact.grant_count}
            testId="impact-grant-count"
          />
          <ImpactMetric
            label={t("impact.assignees")}
            value={draft.impact.assignee_count}
            testId="impact-assignee-count"
          />
          <ImpactMetric
            label={t("impact.expansions")}
            value={draft.impact.expansion_count}
            testId="impact-expansion-count"
          />
          <ImpactMetric
            label={t("impact.revocations")}
            value={draft.impact.revocation_count}
            testId="impact-revocation-count"
          />
        </dl>

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
                <li key={blocker}>{blocker}</li>
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
            className="min-h-11"
            disabled={publishing}
            onClick={() => onOpenChange(false)}
          >
            {t("impact.cancel")}
          </Button>
          <Button
            type="button"
            className="min-h-11"
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
