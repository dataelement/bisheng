/**
 * Publish tab — the shell plus what F054 itself owns (决议-6):
 * the state badge, the copyable entry link and the operational actions.
 *
 * Everything else is a **slot**. The publish pipeline, capability declaration,
 * resource tier and danger zone belong to F055; the visibility section belongs
 * to F056. They are props rather than inline sections so three features can
 * land without three edits to the same JSX block.
 *
 * The entry link is rendered from `app.entry_url` exactly as the backend sent
 * it. Composing it from `location.origin` would produce `localhost:3001/apps/…`
 * in dev — a link that goes nowhere, since `/apps` is not in the vite proxy.
 */
import { Button } from "@/components/bs-ui/button"
import { toast } from "@/components/bs-ui/toast/use-toast"
import type {
  HostedAppDetail,
  HostedAppInstance,
  HostedAppPendingReason,
} from "@/controllers/API/hostedApp"
import { copyText } from "@/utils"
import { Copy, ExternalLink, Loader2 } from "lucide-react"
import { useState } from "react"
import { useTranslation } from "react-i18next"
import {
  useHostedAppActions,
  type HostedAppActionKind,
} from "../../useHostedAppActions"
import {
  pendingAwareStateI18nKey,
  phaseI18nKey,
  stateBadgeClass,
} from "../types"

interface PublishTabProps {
  app: HostedAppDetail
  instance: HostedAppInstance | null
  instanceError?: string
  onChanged: () => void
  /** F055 — pipeline status / capability declaration / resource tier. */
  pipelineSlot?: React.ReactNode
  /** F056 — visibility scope. */
  visibilitySlot?: React.ReactNode
  /** F055 — danger zone (delete lives there on this page). */
  dangerZoneSlot?: React.ReactNode
  /**
   * F055 — the release read model's own verdict on "may this person retry a
   * parked release" (AC-32 / AC-62). `undefined` while that model has not
   * loaded, or could not be: the button then falls back to the state-only rule
   * below, because hiding an owner's only way forward is worse than offering a
   * button the server will refuse.
   */
  canManualPublish?: boolean
  /**
   * F055 — why the application is parked. Refines the state badge: the plain
   * `pending_capacity` label names only the capacity cause, which is the wrong
   * story for a release that built fine and then failed to start.
   */
  pendingReason?: HostedAppPendingReason | null
}

function Section({
  title,
  children,
}: {
  title: string
  children: React.ReactNode
}) {
  return (
    <section className="rounded-md border bg-background-login p-4">
      <h2 className="mb-3 text-sm font-medium">{title}</h2>
      {children}
    </section>
  )
}

export function PublishTab({
  app,
  instance,
  instanceError = "",
  onChanged,
  pipelineSlot = null,
  visibilitySlot = null,
  dangerZoneSlot = null,
  canManualPublish,
  pendingReason = null,
}: PublishTabProps) {
  const { t } = useTranslation()
  const { stopApp, resumeApp, manualPublishApp } = useHostedAppActions({
    onChanged,
  })

  const appRef = { appId: app.app_id, name: app.name, state: app.state }
  const online = app.state === "online"
  const stopped = app.state === "stopped"
  const parked = app.state === "pending_capacity"

  // These calls wait on the orchestrator — taking an app offline sits through
  // `docker stop`'s 10s SIGTERM grace. Without a busy button the wait reads as
  // a dead click, and the second click loses the state race (16102).
  const [pending, setPending] = useState<HostedAppActionKind | null>(null)
  const runAction = async (
    kind: HostedAppActionKind,
    action: (ref: typeof appRef) => Promise<boolean>,
  ) => {
    if (pending) return
    setPending(kind)
    try {
      await action(appRef)
    } finally {
      setPending(null)
    }
  }

  const handleCopy = async () => {
    await copyText(app.entry_url)
    toast({
      title: t("prompt"),
      variant: "success",
      description: t("hostedApp.publish.copied"),
    })
  }

  return (
    <div className="flex flex-col gap-4 pb-6">
      <Section title={t("hostedApp.publish.stateLabel")}>
        <div className="flex flex-wrap items-center gap-3">
          <span
            className={`rounded-sm px-2 py-0.5 text-xs ${stateBadgeClass(app.state)}`}
          >
            {t(pendingAwareStateI18nKey(app.state, pendingReason))}
          </span>
          {online && (
            <Button
              variant="outline"
              size="sm"
              disabled={pending !== null}
              onClick={() => runAction("stop", stopApp)}
            >
              {pending === "stop" && (
                <Loader2 className="mr-1 size-3.5 animate-spin" />
              )}
              {t("hostedApp.publish.stop")}
            </Button>
          )}
          {stopped && (
            <Button
              variant="outline"
              size="sm"
              disabled={pending !== null}
              onClick={() => runAction("resume", resumeApp)}
            >
              {pending === "resume" && (
                <Loader2 className="mr-1 size-3.5 animate-spin" />
              )}
              {t("hostedApp.publish.resume")}
            </Button>
          )}
          {parked && canManualPublish !== false && (
            <Button
              variant="outline"
              size="sm"
              disabled={pending !== null}
              onClick={() => runAction("manualPublish", manualPublishApp)}
            >
              {pending === "manualPublish" && (
                <Loader2 className="mr-1 size-3.5 animate-spin" />
              )}
              {t("hostedApp.publish.manualPublish")}
            </Button>
          )}
        </div>
      </Section>

      <Section title={t("hostedApp.publish.entryLabel")}>
        <div className="flex flex-wrap items-center gap-2">
          <code className="max-w-full break-all rounded bg-muted px-2 py-1 text-xs">
            {app.entry_url}
          </code>
          <Button variant="outline" size="sm" onClick={handleCopy}>
            <Copy className="mr-1 size-3.5" />
            {t("hostedApp.publish.copy")}
          </Button>
          <Button variant="outline" size="sm" asChild>
            <a href={app.entry_url} target="_blank" rel="noreferrer">
              <ExternalLink className="mr-1 size-3.5" />
              {t("hostedApp.publish.open")}
            </a>
          </Button>
        </div>
        {!online && (
          <p className="mt-2 text-xs text-muted-foreground">
            {t("hostedApp.publish.entryInactive")}
          </p>
        )}
      </Section>

      <Section title={t("hostedApp.publish.instanceTitle")}>
        {instance ? (
          <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm md:grid-cols-4">
            <div>
              <dt className="text-xs text-muted-foreground">
                {t("hostedApp.publish.instancePhase")}
              </dt>
              <dd>{t(phaseI18nKey(instance.phase))}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">
                {t("hostedApp.publish.instanceHealth")}
              </dt>
              <dd>{instance.health || "-"}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">
                {t("hostedApp.publish.instanceRestart")}
              </dt>
              <dd>{instance.restart_count ?? 0}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">
                {t("hostedApp.publish.instanceStartedAt")}
              </dt>
              <dd>{instance.started_at || "-"}</dd>
            </div>
          </dl>
        ) : (
          <p className="text-sm text-muted-foreground">
            {instanceError || t("hostedApp.publish.instanceUnavailable")}
          </p>
        )}
      </Section>

      {pipelineSlot}
      {visibilitySlot}
      {dangerZoneSlot}
    </div>
  )
}
