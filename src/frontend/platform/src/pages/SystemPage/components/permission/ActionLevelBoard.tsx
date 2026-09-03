import { Button } from "@/components/bs-ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/bs-ui/dropdownMenu"
import { Switch } from "@/components/bs-ui/switch"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/bs-ui/tooltip"
import type {
  PermissionActionLevel,
  PermissionCatalogAction,
  PermissionCatalogChange,
  PermissionCatalogDraft,
} from "@/controllers/API/permission"
import { cn } from "@/utils"
import { ChevronDown, GripVertical, Info } from "lucide-react"
import { useCallback, useEffect, useMemo, useState } from "react"
import { useTranslation } from "react-i18next"
import { actionLabel, resourceTypeLabel } from "./actionLabels"

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
  const [draftErrorMessage, setDraftErrorMessage] = useState<string | null>(null)
  const [showChangeList, setShowChangeList] = useState(false)
  const [draggingCode, setDraggingCode] = useState<string | null>(null)

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
    setDraftErrorMessage(null)
    setShowChangeList(false)
  }

  useEffect(resetToRelease, [normalizedActions])

  const levelName = useCallback(
    (level: ActionLevelValue) =>
      level === null
        ? t("actionLevel.unassigned")
        : t("actionLevel.level", { level }),
    [t],
  )

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

  // "3 changes" tells the author how much is pending but not what it is, and the
  // impact dialog only counts affected resources. Spell each edit out before
  // anyone commits to publishing it.
  const changeSummaries = useMemo(() => {
    const byCode = new Map(
      normalizedActions.map((action) => [action.code, action]),
    )
    return pendingChanges.map((change) => {
      const action = byCode.get(change.action_code!)
      const name = action
        ? actionLabel(t, action.code, action.name)
        : change.action_code!
      if (change.type === "ASSIGN_ACTION_LEVEL") {
        return t("actionLevel.changeSummary.level", {
          name,
          from: levelName(action?.level ?? null),
          to: levelName(change.level ?? null),
        })
      }
      return t(
        change.active
          ? "actionLevel.changeSummary.enabled"
          : "actionLevel.changeSummary.disabled",
        { name },
      )
    })
  }, [levelName, normalizedActions, pendingChanges, t])

  const handleLevelChange = (actionCode: string, level: ActionLevelValue) => {
    if (disabled || submitting || levels[actionCode] === level) return
    setDraftErrorMessage(null)
    setLevels((current) => ({ ...current, [actionCode]: level }))
  }

  const handleActiveChange = (actionCode: string, active: boolean) => {
    if (disabled || submitting || activeStates[actionCode] === active) return
    setDraftErrorMessage(null)
    setActiveStates((current) => ({ ...current, [actionCode]: active }))
  }

  const handlePublishChanges = async () => {
    if (submitting || pendingChanges.length === 0) return
    setSubmitting(true)
    setDraftErrorMessage(null)
    try {
      onReviewImpact(await onCreateDraft(pendingChanges))
    } catch (error) {
      setDraftErrorMessage(
        typeof error === "string" && error.trim()
          ? error
          : t("actionLevel.draftFailed"),
      )
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <section
      aria-label={t("actionLevel.title")}
      className="flex h-full min-h-0 flex-col gap-4"
    >
      <div className="flex shrink-0 flex-wrap items-start justify-between gap-3">
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
            
            disabled={pendingChanges.length === 0 || submitting}
            onClick={resetToRelease}
          >
            {t("actionLevel.discardChanges")}
          </Button>
          <Button
            type="button"
            
            disabled={pendingChanges.length === 0 || submitting}
            onClick={() => void handlePublishChanges()}
          >
            {t("actionLevel.publishChanges")}
          </Button>
        </div>
      </div>

      {pendingChanges.length > 0 && (
        <div
          className="shrink-0 rounded-lg border border-primary/30 bg-primary/5 px-3 py-2 text-sm text-foreground"
          role="status"
        >
          <div className="flex flex-wrap items-center gap-2">
            <Info aria-hidden="true" className="size-4 shrink-0 text-primary" />
            <span>
              {t("actionLevel.pendingChanges", {
                count: pendingChanges.length,
              })}
            </span>
            <button
              type="button"
              className="text-primary underline-offset-2 hover:underline"
              aria-expanded={showChangeList}
              onClick={() => setShowChangeList((current) => !current)}
            >
              {showChangeList
                ? t("actionLevel.hideChangeList")
                : t("actionLevel.showChangeList")}
            </button>
          </div>
          {showChangeList && (
            <ul className="mt-2 space-y-1 pl-6 text-muted-foreground">
              {changeSummaries.map((summary) => (
                <li key={summary} className="list-disc text-xs">
                  {summary}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {draftErrorMessage && (
        <p
          className="shrink-0 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive"
          role="alert"
        >
          {draftErrorMessage}
        </p>
      )}

      {/* The only scroll area on this tab: the level columns, header and banners stay put. */}
      <TooltipProvider delayDuration={200}>
        <div className="grid min-h-0 flex-1 gap-3 overflow-y-auto pr-1 xl:grid-cols-5">
          {LEVELS.map((level) => {
            const key = levelKey(level)
            const zoneActions = normalizedActions.filter(
              (action) => levels[action.code] === level,
            )
            const isDropTarget =
              draggingCode !== null && levels[draggingCode] !== level
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
                  setDraggingCode(null)
                }}
                className={cn(
                  "flex min-h-56 flex-col rounded-xl border bg-muted/30 p-3 transition-colors",
                  // Unassigned is a normal state, not a warning — it reads as one
                  // more column, distinguished by a dashed edge alone.
                  level === null ? "border-dashed" : "border-border",
                  isDropTarget && "border-primary bg-primary/5",
                )}
                role="region"
                aria-label={levelName(level)}
              >
                <div className="mb-3 flex items-center justify-between gap-2">
                  <h3 className="text-sm font-semibold text-foreground">
                    {levelName(level)}
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
                          setDraggingCode(action.code)
                        }}
                        onDragEnd={() => setDraggingCode(null)}
                        className={cn(
                          "group rounded-lg border bg-background p-2.5 shadow-sm transition-opacity",
                          submitting && "opacity-60",
                          !active && "border-dashed",
                        )}
                      >
                        {/* Name and the on/off switch are the whole card. Everything
                            else earned its own affordance: the resource types sit in
                            a tooltip, and the level lives in the drag handle's menu —
                            a full-width select repeated the drag target on every card
                            and doubled the card's height. */}
                        <div className="flex items-center gap-1.5">
                          <GripVertical
                            aria-hidden="true"
                            className="size-4 shrink-0 cursor-grab text-muted-foreground"
                          />

                          <Tooltip>
                            <TooltipTrigger asChild>
                              <p className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">
                                {actionLabel(t, action.code, action.name)}
                              </p>
                            </TooltipTrigger>
                            <TooltipContent className="max-w-64">
                              <p className="font-medium">
                                {actionLabel(t, action.code, action.name)}
                              </p>
                              <p className="mt-0.5 opacity-80">{action.code}</p>
                              <p className="mt-1 opacity-80">
                                {t("actionLevel.appliesTo")}:{" "}
                                {action.resource_types
                                  .map((resourceType) =>
                                    resourceTypeLabel(t, resourceType),
                                  )
                                  .join("、")}
                              </p>
                            </TooltipContent>
                          </Tooltip>

                          <Switch
                            aria-label={`${t("actionLevel.active")}.${action.code}`}
                            checked={active}
                            disabled={disabled || submitting}
                            onCheckedChange={(checked) =>
                              handleActiveChange(action.code, checked)
                            }
                          />
                        </div>

                        {/* Dragging is the fast path; this is the same move for a
                            keyboard, a touch screen, or anyone who would rather
                            pick than aim. Compact so it does not dominate the card. */}
                        <div className="mt-1.5 flex items-center gap-2 pl-[22px]">
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <button
                                type="button"
                                aria-label={`${t("actionLevel.change")}.${action.code}`}
                                disabled={disabled || submitting}
                                className="inline-flex h-6 items-center gap-1 rounded border px-1.5 text-xs text-muted-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 disabled:cursor-not-allowed disabled:opacity-50"
                              >
                                {levelName(level)}
                                <ChevronDown aria-hidden="true" className="size-3" />
                              </button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="start">
                              <DropdownMenuRadioGroup
                                value={String(level ?? "UNASSIGNED")}
                                onValueChange={(value) =>
                                  handleLevelChange(
                                    action.code,
                                    value === "UNASSIGNED"
                                      ? null
                                      : (Number(value) as PermissionActionLevel),
                                  )
                                }
                              >
                                {LEVELS.map((option) => (
                                  <DropdownMenuRadioItem
                                    key={levelKey(option)}
                                    value={String(option ?? "UNASSIGNED")}
                                  >
                                    {levelName(option)}
                                  </DropdownMenuRadioItem>
                                ))}
                              </DropdownMenuRadioGroup>
                            </DropdownMenuContent>
                          </DropdownMenu>

                          {!active && (
                            <span className="text-xs text-muted-foreground">
                              {t("actionLevel.inactive")}
                            </span>
                          )}
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
      </TooltipProvider>
    </section>
  )
}
