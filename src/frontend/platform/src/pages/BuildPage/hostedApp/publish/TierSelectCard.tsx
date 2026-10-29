/**
 * Resource-tier section of the publish tab's settings panel (AC-61 / AC-06, F055 T067).
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
import { StatusTag, SubSection } from "./Panel"

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

/**
 * Rows that may become a `<SelectItem>`.
 *
 * A Radix item with an empty `value` throws and blanks the whole page, and
 * older backends do send rows like that — so the list is filtered here rather
 * than trusted. Exported because the filter is the guard: a `<SelectContent>`
 * is not mounted until the menu opens, so a render test cannot see the item
 * that would have thrown.
 */
export function selectableTiers(options: TierOption[]): TierOption[] {
  return options.filter((one) => !!one.code)
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
  const selectable = selectableTiers(options)

  return (
    <SubSection data-testid="tier-select-card" label={t("hostedApp.tier.title")}>
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
        <div className="flex flex-col gap-1.5">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
            <span>{tier?.name || tier?.code || t("hostedApp.tier.unknown")}</span>
            {currentSpec && (
              <span className="text-muted-foreground">{currentSpec}</span>
            )}
            {tier?.enabled === false && (
              <StatusTag className="bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300">
                {t("hostedApp.tier.retiredTag")}
              </StatusTag>
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
    </SubSection>
  )
}
