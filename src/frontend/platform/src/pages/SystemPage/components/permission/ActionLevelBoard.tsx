import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogTitle,
} from "@/components/bs-ui/dialog";
import type {
  PermissionActionLevel,
  PermissionCatalogAction,
  PermissionCatalogChange,
  PermissionCatalogDraft,
} from "@/controllers/API/permission";
import { cn } from "@/utils";
import { Alert, Button, Switch, Tooltip, TooltipProvider } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { actionLabel, resourceTypeLabel } from "./actionLabels";

interface ActionLevelBoardProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  actions: PermissionCatalogAction[]
  disabled?: boolean
  onCreateDraft: (
    changes: PermissionCatalogChange[],
  ) => Promise<PermissionCatalogDraft>
  onReviewImpact: (draft: PermissionCatalogDraft) => void
}

const LEVELS: PermissionActionLevel[] = [1, 2, 3, 4]
// Keep legacy unassigned cards reachable without assuming a lower risk level.
const UNASSIGNED_DISPLAY_LEVEL = 4

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

export function ActionLevelBoard({
  open,
  onOpenChange,
  actions,
  disabled = false,
  onCreateDraft,
  onReviewImpact,
}: ActionLevelBoardProps) {
  const { t } = useTranslation("permission")
  const normalizedActions = useMemo(() => uniqueActions(actions), [actions])
  const [levels, setLevels] = useState<Record<string, PermissionActionLevel | null>>({})
  const [activeStates, setActiveStates] = useState<Record<string, boolean>>({})
  const [submitting, setSubmitting] = useState(false)
  const [draftErrorMessage, setDraftErrorMessage] = useState<string | null>(null)
  const [draggingCode, setDraggingCode] = useState<string | null>(null)
  const previousFocus = useRef<HTMLElement | null>(null)

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
  }

  useEffect(resetToRelease, [normalizedActions])

  // Derived from the diff against the published release rather than accumulated
  // per edit, so moving a card back where it came from drops the change instead
  // of queueing a second one.
  const pendingChanges = useMemo<PermissionCatalogChange[]>(() => {
    const changes: PermissionCatalogChange[] = []
    for (const action of normalizedActions) {
      const level = levels[action.code]
      if (level != null && level !== action.level) {
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

  const handleLevelChange = (actionCode: string, level: PermissionActionLevel) => {
    if (disabled || submitting || levels[actionCode] === level) return
    setDraftErrorMessage(null)
    // A legacy unassigned action is effectively disabled even if its stored flag is true.
    if (levels[actionCode] === null) {
      setActiveStates((current) => ({ ...current, [actionCode]: false }))
    }
    setLevels((current) => ({ ...current, [actionCode]: level }))
  }

  const handleActiveChange = (actionCode: string, active: boolean) => {
    if (disabled || submitting || activeStates[actionCode] === active) return
    setDraftErrorMessage(null)
    setActiveStates((current) => ({ ...current, [actionCode]: active }))
  }

  const handleOpenChange = (nextOpen: boolean) => {
    if (submitting) return
    if (!nextOpen) resetToRelease()
    onOpenChange(nextOpen)
  }

  const handleReviewChanges = async () => {
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
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent
        close={false}
        aria-describedby={undefined}
        className="flex max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] max-w-6xl flex-col gap-4 rounded-2xl border-border-base bg-bg-page p-4 shadow-modal dark:bg-bg-page sm:rounded-2xl"
        onOpenAutoFocus={() => {
          previousFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
        }}
        onCloseAutoFocus={(event) => {
          if (!previousFocus.current?.isConnected) return
          event.preventDefault()
          previousFocus.current.focus()
        }}
      >
        <DialogTitle className="shrink-0 text-h4 text-text-1">
          {t("actionLevel.configure")}
        </DialogTitle>

        <div className="min-h-0 space-y-3 overflow-y-auto overscroll-contain">
          {draftErrorMessage && <Alert type="error" description={draftErrorMessage} live />}

          <TooltipProvider>
            <div className="overflow-x-auto">
              <div className="grid min-w-[672px] grid-cols-4 gap-3">
                {LEVELS.map((level) => {
                  const levelName = t(`actionLevel.riskLevels.${level}`)
                  const zoneActions = normalizedActions.filter(
                    (action) => (levels[action.code] ?? action.level ?? UNASSIGNED_DISPLAY_LEVEL) === level,
                  )
                  const isDropTarget = draggingCode !== null && levels[draggingCode] !== level
                  return (
                    <div
                      key={level}
                      data-testid={`action-level-zone-${level}`}
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
                        "flex min-h-72 min-w-0 flex-col gap-2 rounded-xl border border-border-base bg-bg-page px-3 pb-3 pt-2 transition-colors",
                        isDropTarget && "border-blue-500 bg-blue-50",
                      )}
                      role="region"
                      aria-label={levelName}
                    >
                      <div className="flex min-h-7 items-center">
                        <h3 className={cn("text-body font-medium text-text-1", level === 4 && "text-danger")}>
                          {levelName}
                        </h3>
                      </div>

                      {zoneActions.map((action) => {
                        const unassigned = (levels[action.code] ?? action.level) === null
                        const active = !unassigned && (activeStates[action.code] ?? action.active)
                        const name = actionLabel(t, action.code, action.name)
                        const appliesTo = action.resource_types
                          .map((resourceType) => resourceTypeLabel(t, resourceType))
                          .join(t("impact.actionSeparator"))
                        return (
                          <Tooltip
                            key={action.code}
                            side="right"
                            content={
                              <>
                                <p className="font-medium">{name}</p>
                                {action.code === "manage_permission" && <p>{t("actionLevel.managePermissionHint")}</p>}
                                <p>{t("actionLevel.appliesTo")} · {appliesTo}</p>
                                {unassigned && <p>{t("actionLevel.assignLevelHint")}</p>}
                              </>
                            }
                          >
                            <article
                              data-testid={`permission-action-${action.code}`}
                              data-model-eligible={String(active)}
                              tabIndex={0}
                              aria-label={name}
                              draggable={!disabled && !submitting}
                              onDragStart={(event) => {
                                event.dataTransfer.effectAllowed = "move"
                                event.dataTransfer.setData("text/plain", action.code)
                                setDraggingCode(action.code)
                              }}
                              onDragEnd={() => setDraggingCode(null)}
                              className={cn(
                                "rounded-md border border-transparent bg-fill-1 px-2 py-1.5 outline-none hover:border-border-deep focus-within:border-border-deep focus-visible:shadow-focus",
                                !active && "border-dashed border-border-base",
                              )}
                            >
                              <div className="flex min-w-0 items-center gap-1.5">
                                <Outlined.Drag aria-hidden="true" className="size-3.5 shrink-0 cursor-grab text-text-3" />
                                <span className="min-w-0 flex-1 truncate text-body-sm font-medium text-text-1">
                                  {name}
                                </span>
                                <Switch
                                  size="small"
                                  aria-label={`${t("actionLevel.active")} · ${name}`}
                                  checked={active}
                                  disabled={disabled || submitting || unassigned}
                                  onCheckedChange={(checked) => handleActiveChange(action.code, checked)}
                                />
                              </div>
                              <div className="flex items-center gap-1.5 pl-5">
                                <p className="min-w-0 flex-1 truncate text-caption text-text-3">{appliesTo}</p>
                                {!active && (
                                  <span className="shrink-0 text-caption text-text-3">
                                    {t(unassigned ? "actionLevel.unassigned" : "actionLevel.inactive")}
                                  </span>
                                )}
                              </div>
                            </article>
                          </Tooltip>
                        )
                      })}

                      {zoneActions.length === 0 && (
                        <p className="flex flex-1 items-center justify-center py-8 text-center text-caption text-text-3">
                          {t("actionLevel.empty")}
                        </p>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          </TooltipProvider>
        </div>

        <DialogFooter className="shrink-0 flex-row flex-wrap items-center gap-3 sm:justify-between sm:space-x-0">
          <Button type="button" color="default" variant="outlined" disabled={pendingChanges.length === 0 || submitting} onClick={resetToRelease}>
            {t("actionLevel.discardChanges")}
          </Button>
          <div className="flex items-center gap-3 max-sm:ml-auto">
            <Button type="button" color="default" variant="outlined" disabled={submitting} onClick={() => handleOpenChange(false)}>
              {t("impact.cancel")}
            </Button>
            <Button type="button" loading={submitting} disabled={disabled || pendingChanges.length === 0} onClick={() => void handleReviewChanges()}>
              {t("actionLevel.publishChanges")}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
