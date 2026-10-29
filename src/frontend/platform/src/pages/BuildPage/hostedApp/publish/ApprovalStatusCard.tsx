/**
 * Approval / release status card of the publish tab (AC-32 / AC-33 / AC-34 / AC-61).
 *
 * It answers one question — "what is happening with my release, and what can I
 * do about it" — from the single read model behind
 * `GET /api/v1/apps/{id}/publish-status`. It owns no state of its own: every
 * verdict (`can.withdraw`, `can.manual_publish`, `can.submit`) is the server's,
 * re-checked server-side when acted on, so the card can be wrong about a button
 * without ever being wrong about an outcome.
 *
 * Three things here are deliberate and easy to "tidy" away:
 *
 * - **The rejection reason is never truncated** (AC-33). A reason an owner can
 *   only half read is a resubmission of the same thing; it wraps instead.
 * - **Parked has two causes and two remedies.** "Out of room" says wait or ask
 *   for capacity; "it would not start" says read the run log. Merging the copy
 *   sends half the owners to debug something that is not broken.
 * - **Withdraw goes to the approval centre's endpoint**, which enforces
 *   "applicant only" itself. This card only decides whether the button is drawn.
 *
 * The capability list and the resource tier are *not* here either: they say
 * what the release runs with, not where it stands, and live in the tab's
 * settings column.
 *
 * The manual-publish button is *not* here: F054's shell already renders it next
 * to the state badge, and it now takes `can.manual_publish` from this same read
 * model. Two buttons doing one thing on one screen is worse than either.
 */
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
import { Button } from "@bisheng/ui"
import { notification } from "@bisheng/ui"
import {
  getHostedAppErrorMessage,
  withdrawApprovalApi,
  type HostedAppDetail,
  type HostedAppPublishStatus,
} from "@/controllers/API/hostedApp"
import { AlertTriangle, Loader2 } from "lucide-react"
import { useState } from "react"
import { useTranslation } from "react-i18next"
import {
  approvalStatusBadgeClass,
  approvalStatusI18nKey,
  pendingReasonI18nKey,
} from "../types"
import { OwnerPreviewCard } from "./OwnerPreviewCard"
import { Field, formatTimestamp, Panel, StatusTag } from "./Panel"
import { SchemaChangeNotice } from "./SchemaChangeNotice"

interface ApprovalStatusCardProps {
  app: HostedAppDetail
  status: HostedAppPublishStatus | null
  loading: boolean
  /** The viewer may see the application but not its release state. */
  forbidden: boolean
  errorMessage: string
  /** Re-read the release state and the page shell after a withdraw. */
  onChanged: () => void
}

export function ApprovalStatusCard({
  app,
  status,
  loading,
  forbidden,
  errorMessage,
  onChanged,
}: ApprovalStatusCardProps) {
  const { t } = useTranslation()
  const [withdrawing, setWithdrawing] = useState(false)

  const approval = status?.approval ?? null
  // Fall back to the shell's own state so the card still explains a parked
  // application when the read model itself could not be loaded.
  const parked = (status?.app_state ?? app.state) === "pending_capacity"
  const canWithdraw = !!status?.can?.withdraw && !!approval?.instance_id
  // RT-03 AC 11 — the server decides (owner, request pending); the card only
  // needs the version under review to point the preview at.
  const previewVersionId =
    status?.can?.preview && approval?.version_id ? approval.version_id : null

  const runWithdraw = async (instanceId: number) => {
    setWithdrawing(true)
    try {
      await withdrawApprovalApi(instanceId)
      notification.open({
        title: t("prompt"),
        type: "success",
        description: t("hostedApp.publishStatus.withdrawDone"),
      })
      onChanged()
    } catch (error) {
      notification.open({
        title: t("prompt"),
        type: "error",
        description:
          getHostedAppErrorMessage(error) ||
          t("hostedApp.publishStatus.withdrawFailed"),
      })
    } finally {
      setWithdrawing(false)
    }
  }

  const handleWithdraw = () => {
    const instanceId = approval?.instance_id
    if (!instanceId || withdrawing) return
    bsConfirm({
      title: t("hostedApp.publishStatus.withdrawTitle"),
      desc: t("hostedApp.publishStatus.withdrawDesc", { name: app.name }),
      okTxt: t("hostedApp.publishStatus.withdraw"),
      onOk(next: () => void) {
        next()
        void runWithdraw(instanceId)
      },
    })
  }

  // Releases are submitted through the CLI; keep its guidance in the panel.
  const actions = (
    <>
      {canWithdraw && (
        <Button
          variant="outline"
          size="sm"
          disabled={withdrawing}
          onClick={handleWithdraw}
        >
          {withdrawing && <Loader2 className="mr-1 size-3.5 animate-spin" />}
          {t("hostedApp.publishStatus.withdraw")}
        </Button>
      )}
    </>
  )

  return (
    <Panel
      title={t("hostedApp.publishStatus.title")}
      description={t("hostedApp.publishStatus.submitDisabledHint")}
      actions={actions}
    >
      {loading && (
        <p className="text-sm text-muted-foreground">
          {t("hostedApp.publishStatus.loading")}
        </p>
      )}

      {!loading && forbidden && (
        <p className="text-sm text-muted-foreground">
          {t("hostedApp.publishStatus.noPermission")}
        </p>
      )}

      {!loading && !forbidden && !status && (
        <p className="text-sm text-muted-foreground">
          {errorMessage || t("hostedApp.publishStatus.loadFailed")}
        </p>
      )}

      {!loading && !!status && (
        <div className="flex flex-col gap-4">
          {approval ? (
            <dl className="grid grid-cols-2 gap-x-6 gap-y-4">
              <Field label={t("hostedApp.publishStatus.approvalLabel")}>
                <StatusTag className={approvalStatusBadgeClass(approval.status)}>
                  {t(approvalStatusI18nKey(approval.status))}
                </StatusTag>
              </Field>
              <Field label={t("hostedApp.publishStatus.approvers")}>
                {approval.approver_names?.length
                  ? approval.approver_names.join(", ")
                  : "-"}
              </Field>
              <Field label={t("hostedApp.publishStatus.submittedAt")}>
                <span className="tabular-nums">
                  {formatTimestamp(approval.submitted_at)}
                </span>
              </Field>
              <Field label={t("hostedApp.publishStatus.decidedAt")}>
                <span className="tabular-nums">
                  {formatTimestamp(approval.decided_at)}
                </span>
              </Field>
            </dl>
          ) : (
            <p className="text-sm text-muted-foreground">
              {t("hostedApp.publishStatus.approvalNone")}
            </p>
          )}

          {!!approval?.reject_reason && (
            <div className="rounded-md border border-red-200 bg-red-50 p-3 dark:border-red-900 dark:bg-red-950">
              <p className="text-xs text-muted-foreground">
                {t("hostedApp.publishStatus.rejectReason")}
              </p>
              {/* Full text, wrapped — AC-33 forbids truncation. */}
              <p className="mt-1 whitespace-pre-wrap break-words text-sm">
                {approval.reject_reason}
              </p>
            </div>
          )}

          {!!previewVersionId && (
            <OwnerPreviewCard appId={app.app_id} versionId={previewVersionId} />
          )}

          {parked && (
            <div className="flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 p-3 dark:border-amber-800 dark:bg-amber-950">
              <AlertTriangle
                aria-hidden="true"
                className="mt-0.5 size-4 shrink-0 text-amber-600 dark:text-amber-400"
              />
              <div className="min-w-0">
                <p className="text-sm font-medium">
                  {t("hostedApp.publishStatus.pendingTitle")}
                </p>
                <p className="mt-1 text-sm">
                  {t(pendingReasonI18nKey(status.pending_reason))}
                </p>
              </div>
            </div>
          )}

          {/* AC-09 / AC-61 — what the pending release does to the declared
              tables. Confirmed on the CLI at submit time; shown here, never
              asked again. Renders nothing when the read model sends null. */}
          <SchemaChangeNotice change={status.schema_change} />
        </div>
      )}
    </Panel>
  )
}
