import { Button } from "@/components/bs-ui/button"
import { Switch } from "@/components/bs-ui/switch"
import type {
  PermissionActionLevel,
  PermissionCatalogAction,
  PermissionCatalogChange,
  PermissionCatalogDraft,
} from "@/controllers/API/permission"
import { cn } from "@/utils"
import { GripVertical, ShieldAlert } from "lucide-react"
import { useEffect, useMemo, useState } from "react"
import { useTranslation } from "react-i18next"

interface ActionLevelBoardProps {
  actions: PermissionCatalogAction[]
  disabled?: boolean
  onCreateDraft: (
    changes: PermissionCatalogChange[],
  ) => Promise<PermissionCatalogDraft>
  onReviewImpact: (draft: PermissionCatalogDraft) => void
}

type ActionLevelValue = PermissionActionLevel | null

const LEVELS: ActionLevelValue[] = [null, 1, 2, 3, 4]

function uniqueActions(
  actions: PermissionCatalogAction[],
): PermissionCatalogAction[] {
  const unique = new Map<string, PermissionCatalogAction>()
  for (const action of [...actions].sort(
    (left, right) => left.sort_order - right.sort_order,
  )) {
    if (!unique.has(action.code)) unique.set(action.code, action)
  }
  return Array.from(unique.values())
}

function levelKey(level: ActionLevelValue): string {
  return level === null ? "unassigned" : String(level)
}

export function ActionLevelBoard({
  actions,
  disabled = false,
  onCreateDraft,
  onReviewImpact,
}: ActionLevelBoardProps) {
  const { t } = useTranslation("permission")
  const normalizedActions = useMemo(() => uniqueActions(actions), [actions])
  const [levels, setLevels] = useState<Record<string, ActionLevelValue>>({})
  const [activeStates, setActiveStates] = useState<Record<string, boolean>>({})
  const [submitting, setSubmitting] = useState(false)
  const [draftFailed, setDraftFailed] = useState(false)

  const resetToRelease = () => {
    setLevels(
      Object.fromEntries(
        normalizedActions.map((action) => [action.code, action.level]),
      ),
    )
    setActiveStates(
      Object.fromEntries(
        normalizedActions.map((action) => [action.code, action.active]),
      ),
    )
    setDraftFailed(false)
  }

  useEffect(resetToRelease, [normalizedActions])

  // Derived from the diff against the published release rather than accumulated
  // per edit, so moving a card back where it came from drops the change instead
  // of queueing a second one.
  const pendingChanges = useMemo<PermissionCatalogChange[]>(() => {
    const changes: PermissionCatalogChange[] = []
    for (const action of normalizedActions) {
      const level = levels[action.code]
      if (level !== undefined && level !== action.level) {
        changes.push({
          type: "ASSIGN_ACTION_LEVEL",
          action_code: action.code,
          level,
        })
      }
      const active = activeStates[action.code]
      if (active !== undefined && active !== action.active) {
        changes.push({
          type: "SET_ACTION_ACTIVE",
          action_code: action.code,
          active,
        })
      }
    }
    return changes
  }, [normalizedActions, levels, activeStates])

  const handleLevelChange = (actionCode: string, level: ActionLevelValue) => {
    if (disabled || submitting || levels[actionCode] === level) return
    setDraftFailed(false)
    setLevels((current) => ({ ...current, [actionCode]: level }))
  }

  const handleActiveChange = (actionCode: string, active: boolean) => {
    if (disabled || submitting || activeStates[actionCode] === active) return
    setDraftFailed(false)
    setActiveStates((current) => ({ ...current, [actionCode]: active }))
  }

  const handlePublishChanges = async () => {
    if (submitting || pendingChanges.length === 0) return
    setSubmitting(true)
    setDraftFailed(false)
    try {
      onReviewImpact(await onCreateDraft(pendingChanges))
    } catch {
      setDraftFailed(true)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <section
      aria-label={t("actionLevel.title")}
      className="flex min-h-0 flex-col gap-4"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-foreground">
            {t("actionLevel.title")}
          </h2>
          <p className="mt-1 text-sm leading-6 text-muted-foreground">
            {t("actionLevel.description")}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            className="min-h-11"
            disabled={pendingChanges.length === 0 || submitting}
            onClick={resetToRelease}
          >
            {t("actionLevel.discardChanges")}
          </Button>
          <Button
            type="button"
            className="min-h-11"
            disabled={pendingChanges.length === 0 || submitting}
            onClick={() => void handlePublishChanges()}
          >
            {t("actionLevel.publishChanges")}
          </Button>
        </div>
      </div>

      {pendingChanges.length > 0 && (
        <div
          className="flex items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-900"
          role="status"
        >
          <ShieldAlert aria-hidden="true" className="size-4 shrink-0" />
          <span>
            {t("actionLevel.pendingChanges", {
              count: pendingChanges.length,
            })}
          </span>
        </div>
      )}

      {draftFailed && (
        <p
          className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900"
          role="alert"
        >
          {t("actionLevel.draftFailed")}
        </p>
      )}

      <div className="grid min-h-0 gap-3 xl:grid-cols-5">
        {LEVELS.map((level) => {
          const key = levelKey(level)
          const zoneActions = normalizedActions.filter(
            (action) => levels[action.code] === level,
          )
          return (
            <div
              key={key}
              data-testid={`action-level-zone-${key}`}
              onDragOver={(event) => {
                event.preventDefault()
                event.dataTransfer.dropEffect = "move"
              }}
              onDrop={(event) => {
                event.preventDefault()
                const actionCode = event.dataTransfer.getData("text/plain")
                if (actionCode) handleLevelChange(actionCode, level)
              }}
              className={cn(
                "min-h-56 rounded-xl border bg-muted/30 p-3 transition-colors",
                level === null
                  ? "border-dashed border-amber-300 bg-amber-50/60"
                  : "border-border",
              )}
              role="region"
              aria-label={
                level === null
                  ? t("actionLevel.unassigned")
                  : t("actionLevel.level", { level })
              }
            >
              <div className="mb-3 flex items-center justify-between gap-2">
                <h3 className="text-sm font-semibold text-foreground">
                  {level === null
                    ? t("actionLevel.unassigned")
                    : t("actionLevel.level", { level })}
                </h3>
                <span className="rounded-full bg-background px-2 py-0.5 text-xs tabular-nums text-muted-foreground">
                  {zoneActions.length}
                </span>
              </div>

              <div className="flex flex-col gap-2">
                {zoneActions.map((action) => {
                  const active = activeStates[action.code] ?? action.active
                  return (
                    <article
                      key={action.code}
                      data-testid={`permission-action-${action.code}`}
                      data-model-eligible={String(level !== null && active)}
                      draggable={!disabled && !submitting}
                      onDragStart={(event) => {
                        event.dataTransfer.effectAllowed = "move"
                        event.dataTransfer.setData("text/plain", action.code)
                      }}
                      className={cn(
                        "rounded-lg border bg-background p-3 shadow-sm transition-opacity",
                        submitting && "opacity-60",
                      )}
                    >
                      <div className="flex items-start gap-2">
                        <GripVertical
                          aria-hidden="true"
                          className="mt-1 size-4 shrink-0 text-muted-foreground"
                        />
                        <div className="min-w-0 flex-1">
                          <div className="flex items-start justify-between gap-2">
                            <div className="min-w-0">
                              <p className="truncate text-sm font-medium text-foreground">
                                {action.name}
                              </p>
                              <p className="truncate text-xs text-muted-foreground">
                                {action.code}
                              </p>
                            </div>
                            <Switch
                              aria-label={`${t("actionLevel.active")}.${action.code}`}
                              checked={active}
                              disabled={disabled || submitting}
                              onCheckedChange={(checked) =>
                                handleActiveChange(action.code, checked)
                              }
                            />
                          </div>

                          {!active && (
                            <p className="mt-2 text-xs font-medium text-red-700">
                              {t("actionLevel.inactive")}
                            </p>
                          )}

                          <div className="mt-2 flex flex-wrap gap-1">
                            {action.resource_types.map((resourceType) => (
                              <span
                                key={resourceType}
                                className="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground"
                              >
                                {resourceType}
                              </span>
                            ))}
                          </div>

                          <label className="mt-3 block text-xs font-medium text-muted-foreground">
                            <span className="sr-only">
                              {`${t("actionLevel.change")}.${action.code}`}
                            </span>
                            <select
                              aria-label={`${t("actionLevel.change")}.${action.code}`}
                              value={level ?? "UNASSIGNED"}
                              disabled={disabled || submitting}
                              onChange={(event) =>
                                handleLevelChange(
                                  action.code,
                                  event.target.value === "UNASSIGNED"
                                    ? null
                                    : (Number(
                                        event.target.value,
                                      ) as PermissionActionLevel),
                                )
                              }
                              className="min-h-11 w-full rounded-md border border-input bg-background px-2 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                            >
                              <option value="UNASSIGNED">
                                {t("actionLevel.unassigned")}
                              </option>
                              {[1, 2, 3, 4].map((value) => (
                                <option key={value} value={value}>
                                  {t("actionLevel.level", { level: value })}
                                </option>
                              ))}
                            </select>
                          </label>
                        </div>
                      </div>
                    </article>
                  )
                })}

                {zoneActions.length === 0 && (
                  <p className="rounded-lg border border-dashed px-3 py-8 text-center text-xs text-muted-foreground">
                    {t("actionLevel.empty")}
                  </p>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </section>
  )
}
