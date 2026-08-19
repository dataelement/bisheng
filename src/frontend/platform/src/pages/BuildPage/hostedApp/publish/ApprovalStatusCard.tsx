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
 * The manual-publish button is *not* here: F054's shell already renders it next
 * to the state badge, and it now takes `can.manual_publish` from this same read
 * model. Two buttons doing one thing on one screen is worse than either.
 */
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
import { Button } from "@/components/bs-ui/button"
import { toast } from "@/components/bs-ui/toast/use-toast"
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

interface FieldProps {
  label: string
  value: string
}

function Field({ label, value }: FieldProps) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="break-all text-sm">{value}</dd>
    </div>
  )
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
  const tier = status?.tier ?? null
  // Fall back to the shell's own state so the card still explains a parked
  // application when the read model itself could not be loaded.
  const parked = (status?.app_state ?? app.state) === "pending_capacity"
  const canWithdraw = !!status?.can?.withdraw && !!approval?.instance_id
  const schemaChange = status?.schema_change ?? null

  const runWithdraw = async (instanceId: number) => {
    setWithdrawing(true)
    try {
      await withdrawApprovalApi(instanceId)
      toast({
        title: t("prompt"),
        variant: "success",
        description: t("hostedApp.publishStatus.withdrawDone"),
      })
      onChanged()
    } catch (error) {
      toast({
        title: t("prompt"),
        variant: "error",
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

  const tierSpec =
    tier && tier.cpu_millicores !== null && tier.memory_mb !== null
      ? t("hostedApp.publishStatus.tierSpec", {
          cpu: tier.cpu_millicores,
          memory: tier.memory_mb,
        })
      : ""

  return (
    <section className="rounded-md border bg-background-login p-4">
      <h2 className="mb-3 text-sm font-medium">
        {t("hostedApp.publishStatus.title")}
      </h2>

      {/* AC-06 — every application in this release arrives through the CLI and
          has no draft workspace on the platform, so there is nothing for a
          submit button to submit. Shown disabled with the real remedy rather
          than hidden: an owner looking for "where do I publish" needs to be
          told where publishing happens, not to find nothing. */}
      <div className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-1">
        <Button variant="outline" size="sm" disabled>
          {t("hostedApp.publishStatus.submit")}
        </Button>
        <p className="text-xs text-muted-foreground">
          {t("hostedApp.publishStatus.submitDisabledHint")}
        </p>
      </div>

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
          {!!tier && (
            <dl className="grid grid-cols-2 gap-x-6 gap-y-2 md:grid-cols-4">
              <Field
                label={t("hostedApp.publishStatus.tierLabel")}
                value={[tier.name || tier.code || "-", tierSpec]
                  .filter(Boolean)
                  .join(" · ")}
              />
            </dl>
          )}

          {approval ? (
            <div className="flex flex-col gap-3">
              <div className="flex flex-wrap items-center gap-3">
                <span
                  className={`rounded-sm px-2 py-0.5 text-xs ${approvalStatusBadgeClass(approval.status)}`}
                >
                  {t(approvalStatusI18nKey(approval.status))}
                </span>
                {canWithdraw && (
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={withdrawing}
                    onClick={handleWithdraw}
                  >
                    {withdrawing && (
                      <Loader2 className="mr-1 size-3.5 animate-spin" />
                    )}
                    {t("hostedApp.publishStatus.withdraw")}
                  </Button>
                )}
              </div>
              <dl className="grid grid-cols-2 gap-x-6 gap-y-2 md:grid-cols-3">
                <Field
                  label={t("hostedApp.publishStatus.submittedAt")}
                  value={approval.submitted_at || "-"}
                />
                <Field
                  label={t("hostedApp.publishStatus.decidedAt")}
                  value={approval.decided_at || "-"}
                />
                <Field
                  label={t("hostedApp.publishStatus.approvers")}
                  value={
                    approval.approver_names?.length
                      ? approval.approver_names.join(", ")
                      : "-"
                  }
                />
              </dl>
              {!!approval.reject_reason && (
                <div className="rounded-md border border-red-300 bg-red-50 p-3 dark:border-red-800 dark:bg-red-950">
                  <p className="mb-1 text-xs text-muted-foreground">
                    {t("hostedApp.publishStatus.rejectReason")}
                  </p>
                  {/* Full text, wrapped — AC-33 forbids truncation. */}
                  <p className="whitespace-pre-wrap break-words text-sm">
                    {approval.reject_reason}
                  </p>
                </div>
              )}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              {t("hostedApp.publishStatus.approvalNone")}
            </p>
          )}

          {parked && (
            <div className="flex flex-wrap items-start gap-2 rounded-md border border-amber-300 bg-amber-50 p-3 dark:border-amber-700 dark:bg-amber-950">
              <AlertTriangle
                aria-hidden="true"
                className="mt-0.5 size-4 shrink-0 text-amber-600 dark:text-amber-400"
              />
              <div>
                <p className="text-sm font-medium">
                  {t("hostedApp.publishStatus.pendingTitle")}
                </p>
                <p className="mt-1 text-sm">
                  {t(pendingReasonI18nKey(status.pending_reason))}
                </p>
              </div>
            </div>
          )}

          {/* Structure-change notice. The read model always sends `null` in
              this release (the schema wave is deferred), so this block is
              expected never to render yet — it exists so landing that wave is
              a backend change alone. */}
          {!!schemaChange && (
            <div className="rounded-md border border-amber-300 bg-amber-50 p-3 dark:border-amber-700 dark:bg-amber-950">
              <p className="text-sm font-medium">
                {t("hostedApp.publishStatus.schemaChangeTitle")}
              </p>
              {!!schemaChange.summary && (
                <p className="mt-1 whitespace-pre-wrap break-words text-sm">
                  {schemaChange.summary}
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  )
}
