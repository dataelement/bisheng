/**
 * Declared platform capabilities of a release, in plain language (F055 AC-61 / AC-63).
 *
 * The list answers one question — "what does this application get from the
 * platform, and does it still have it" — and it answers it for the release the
 * owner is about to get: the pending one while an iteration is on its way,
 * otherwise the running one. The backend picks which; this only renders.
 *
 * Two things it deliberately does not do:
 *
 * - **It never says "healthy" by omission.** A capability that no longer
 *   resolves is marked 「已失效」 with the reason next to it, because the whole
 *   reason an owner opens this list is to find out which of their six
 *   declarations broke. An unmarked row means "checked just now and fine",
 *   which is true: the mark is computed per request, nothing is stored.
 * - **It offers no way to edit a declaration.** Capabilities are declared in
 *   `bisheng-app.yaml` and take effect through a publish; a control here would
 *   be a second, unapproved way to change what an application may call.
 *   AC-54's "no provider account or endpoint configuration in the workbench"
 *   is kept by this file having no inputs at all.
 */
import type { HostedAppCapability } from "@/controllers/API/hostedApp"
import { Database, Sparkles } from "lucide-react"
import { useTranslation } from "react-i18next"

interface CapabilityListCardProps {
  capabilities: HostedAppCapability[] | undefined
}

/** Reason vocabulary the backend sends; anything else falls back to the generic line. */
const REASON_KEYS: Record<string, string> = {
  revoked: "hostedApp.publishStatus.capabilityReasonRevoked",
  ambiguous: "hostedApp.publishStatus.capabilityReasonAmbiguous",
  unresolvable: "hostedApp.publishStatus.capabilityReasonUnresolvable",
}

function reasonI18nKey(reason: string): string {
  return REASON_KEYS[reason] ?? "hostedApp.publishStatus.capabilityReasonUnresolvable"
}

function kindI18nKey(kind: string): string {
  return kind === "model"
    ? "hostedApp.publishStatus.capabilityKindModel"
    : "hostedApp.publishStatus.capabilityKindKnowledge"
}

export function CapabilityListCard({ capabilities }: CapabilityListCardProps) {
  const { t } = useTranslation()
  const rows = capabilities ?? []

  return (
    <section data-testid="capability-list-card" className="flex flex-col gap-2">
      <h3 className="text-sm font-medium">
        {t("hostedApp.publishStatus.capabilityTitle")}
      </h3>
      {rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {t("hostedApp.publishStatus.capabilityNone")}
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {rows.map((capability, index) => {
            const Icon = capability.kind === "model" ? Sparkles : Database
            return (
              <li
                key={`${capability.kind}-${capability.name}-${index}`}
                className="flex flex-wrap items-center gap-2 rounded-md border border-border bg-background px-3 py-2 text-sm"
              >
                <Icon aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
                <span className="text-muted-foreground">
                  {t(kindI18nKey(capability.kind))}
                </span>
                <span className="min-w-0 break-all font-medium">{capability.name}</span>
                {capability.revoked && (
                  <>
                    <span className="rounded-sm bg-red-100 px-1.5 py-0.5 text-xs text-red-700 dark:bg-red-900 dark:text-red-200">
                      {t("hostedApp.publishStatus.capabilityRevokedTag")}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      {t(reasonI18nKey(capability.reason))}
                    </span>
                  </>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
