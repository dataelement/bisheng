/**
 * Resource-tier card of the publish tab (AC-61 / AC-06, F055 T067).
 *
 * Two states, and which one an application gets is decided by the server, not
 * here:
 *
 * * **Read-only** — every application in this volume. It arrived through
 *   `bisheng deploy`, so its tier is whatever `bisheng-app.yaml` declared, and
 *   the only honest thing the page can do is show which one and say where it
 *   is changed. A disabled dropdown would look like a control that is broken;
 *   a sentence naming the file is a control the reader can actually use.
 * * **Selectable** — an application submitted from inside the platform, which
 *   arrives with PRD-2's in-platform authoring entry. `can.submit` is the
 *   switch and it is `false` for every application today (AC-06), so this
 *   branch is wired and unreachable in this release: the card takes the tier
 *   list as a prop rather than fetching it, because the tier list endpoint is
 *   a platform-super-admin surface (16260) and an owner cannot read it.
 *
 * CPU is shown in cores, not millicores. The system page's tier editor spells
 * millicores because it edits exact numbers; an application owner is reading,
 * and "0.5 核" is the sentence they would say out loud.
 */
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/bs-ui/select"
import type { HostedAppTier } from "@/controllers/API/hostedApp"
import { useTranslation } from "react-i18next"

export interface TierOption {
  code: string
  name: string
  cpu_millicores: number | null
  memory_mb: number | null
}

interface TierSelectCardProps {
  /** The tier the current or pending release runs on; `null` before a first release. */
  tier: HostedAppTier | null | undefined
  /**
   * AC-06 — whether this application can be submitted from the platform at
   * all. `false` (today, always) makes the card read-only.
   */
  canSubmit?: boolean
  /** Selectable tiers, for the PRD-2 branch. Empty in this release. */
  options?: TierOption[]
  value?: string
  onChange?: (code: string) => void
}

/** `500` → `0.5`, `2000` → `2`. `null` when the spec is unknown. */
export function coresOf(millicores: number | null | undefined): number | null {
  if (typeof millicores !== "number" || !Number.isFinite(millicores) || millicores <= 0) {
    return null
  }
  return Math.round((millicores / 1000) * 100) / 100
}

export function TierSelectCard({
  tier,
  canSubmit = false,
  options = [],
  value = "",
  onChange,
}: TierSelectCardProps) {
  const { t } = useTranslation()

  const spec = (cpu: number | null | undefined, memory: number | null | undefined) => {
    const cores = coresOf(cpu)
    const parts: string[] = []
    if (cores !== null) parts.push(t("hostedApp.tier.cores", { count: cores }))
    if (typeof memory === "number" && memory > 0) {
      parts.push(t("hostedApp.tier.memory", { count: memory }))
    }
    return parts.join(" · ")
  }

  const currentSpec = spec(tier?.cpu_millicores, tier?.memory_mb)
  // A tier row whose `code` is empty would crash the Radix item and take the
  // page down with it; the list is filtered rather than trusted.
  const selectable = options.filter((one) => !!one.code)

  return (
    <section
      data-testid="tier-select-card"
      className="rounded-md border bg-background-login p-4"
    >
      <h2 className="mb-3 text-sm font-medium">{t("hostedApp.tier.title")}</h2>
      {canSubmit && selectable.length > 0 ? (
        <div className="flex flex-col gap-2">
          <Select value={value} onValueChange={(next) => onChange?.(next)}>
            <SelectTrigger className="w-72">
              <SelectValue placeholder={t("hostedApp.tier.placeholder")} />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {selectable.map((one) => (
                  <SelectItem key={one.code} value={one.code}>
                    {one.name}
                    {spec(one.cpu_millicores, one.memory_mb)
                      ? ` · ${spec(one.cpu_millicores, one.memory_mb)}`
                      : ""}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
          <p className="text-xs text-muted-foreground">
            {t("hostedApp.tier.effectiveHint")}
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="rounded-sm bg-muted px-2 py-0.5">
              {tier?.name || tier?.code || t("hostedApp.tier.unknown")}
            </span>
            {currentSpec && (
              <span className="text-muted-foreground">{currentSpec}</span>
            )}
            {tier?.enabled === false && (
              <span className="rounded-sm bg-amber-100 px-1.5 py-0.5 text-xs text-amber-800 dark:bg-amber-900 dark:text-amber-100">
                {t("hostedApp.tier.retiredTag")}
              </span>
            )}
          </div>
          <p className="text-xs text-muted-foreground">
            {t("hostedApp.tier.cliOnlyHint")}
          </p>
          {tier?.enabled === false && (
            <p className="text-xs text-muted-foreground">
              {t("hostedApp.tier.retiredHint")}
            </p>
          )}
        </div>
      )}
    </section>
  )
}
