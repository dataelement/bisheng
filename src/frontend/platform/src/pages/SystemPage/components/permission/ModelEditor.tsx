import { Button } from "@/components/bs-ui/button"
import { Checkbox } from "@/components/bs-ui/checkBox"
import { Input } from "@/components/bs-ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/bs-ui/select"
import { Switch } from "@/components/bs-ui/switch"
import type {
  PermissionCatalogAction,
  PermissionCatalogChange,
  PermissionCatalogDraft,
  PermissionCatalogModel,
} from "@/controllers/API/permission"
import { ShieldAlert } from "lucide-react"
import { useEffect, useMemo, useState } from "react"
import { useTranslation } from "react-i18next"
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
import { actionLabel } from "./actionLabels"

const BLANK_PRESET_KEY = "__blank__"

interface PermissionModelPreset {
  key: string
  name: string
  action_codes: string[]
}

interface ModelEditorProps {
  model: PermissionCatalogModel
  actions: PermissionCatalogAction[]
  presets?: PermissionModelPreset[]
  createMode?: boolean
  disabled?: boolean
  onInitializePreset?: (preset: PermissionModelPreset) => void
  onCreateDraft: (
    changes: PermissionCatalogChange[],
  ) => Promise<PermissionCatalogDraft>
  onDeleteModel: (modelKey: string) => Promise<PermissionCatalogDraft>
  onReviewImpact: (draft: PermissionCatalogDraft) => void
}

function selectedActionCodes(
  actions: PermissionCatalogAction[],
  selected: Set<string>,
): string[] {
  return [...actions]
    .sort((left, right) => left.sort_order - right.sort_order)
    .filter((action) => action.level !== null && selected.has(action.code))
    .map((action) => action.code)
}

export function ModelEditor({
  model,
  actions,
  presets = [],
  createMode = false,
  disabled = false,
  onInitializePreset,
  onCreateDraft,
  onDeleteModel,
  onReviewImpact,
}: ModelEditorProps) {
  const { t } = useTranslation("permission")
  const [name, setName] = useState(model.name)
  const [active, setActive] = useState(model.active)
  const [allowSameLevel, setAllowSameLevel] = useState(
    model.allow_same_level,
  )
  const [selected, setSelected] = useState(
    () => new Set(model.action_codes),
  )
  const [selectedPreset, setSelectedPreset] = useState("")
  const [draft, setDraft] = useState<PermissionCatalogDraft | null>(null)
  const [saving, setSaving] = useState(false)
  const [deleteBlocked, setDeleteBlocked] = useState(false)

  const isStandard = model.kind === "STANDARD"
  const eligibleActions = useMemo(
    () =>
      [...actions]
        .sort((left, right) => left.sort_order - right.sort_order)
        .filter(
          (action) =>
            action.level !== null ||
            (!isStandard && selected.has(action.code)),
        ),
    [actions, isStandard, selected],
  )
  const effectiveSelectedActions = useMemo(
    () =>
      actions.filter(
        (action) =>
          action.active &&
          action.level !== null &&
          selected.has(action.code),
      ),
    [actions, selected],
  )
  const derivedLevel = isStandard
    ? model.derived_level
    : effectiveSelectedActions.reduce<number | null>(
        (highest, action) =>
          highest === null
            ? action.level
            : Math.max(highest, action.level ?? highest),
        null,
      )
  // One group per level, in level order, with anything unusable (an action that
  // lost its level or was switched off while this model still selects it) last.
  const actionGroups = useMemo(() => {
    const groups = new Map<string, PermissionCatalogAction[]>()
    for (const action of eligibleActions) {
      const key = action.level === null ? "unassigned" : String(action.level)
      const bucket = groups.get(key)
      if (bucket) bucket.push(action)
      else groups.set(key, [action])
    }
    return [...groups.entries()]
      .sort(([left], [right]) => {
        if (left === "unassigned") return 1
        if (right === "unassigned") return -1
        return Number(left) - Number(right)
      })
      .map(([key, groupActions]) => ({
        key,
        title:
          key === "unassigned"
            ? t("actionLevel.unassigned")
            : t("actionLevel.level", { level: Number(key) }),
        actions: groupActions,
        selectedCount: groupActions.filter((action) =>
          selected.has(action.code),
        ).length,
      }))
  }, [eligibleActions, selected, t])

  const hasInvalidSelection = [...selected].some((actionCode) => {
    const action = actions.find((item) => item.code === actionCode)
    return !action || !action.active || action.level === null
  })
  const managePermissionAction = actions.find(
    (action) => action.code === "manage_permission",
  )
  const canAllowSameLevel =
    selected.has("manage_permission") &&
    managePermissionAction?.active === true &&
    managePermissionAction.level !== null

  useEffect(() => {
    setName(model.name)
    setActive(model.active)
    setAllowSameLevel(model.allow_same_level)
    setSelected(new Set(model.action_codes))
    setSelectedPreset("")
    setDraft(null)
    setDeleteBlocked(false)
  }, [model])

  const handleActionChange = (actionCode: string, checked: boolean) => {
    setSelected((current) => {
      const next = new Set(current)
      if (checked) next.add(actionCode)
      else next.delete(actionCode)
      return next
    })
    if (actionCode === "manage_permission" && !checked) {
      setAllowSameLevel(false)
    }
  }

  const handleSave = async () => {
    if (disabled || saving) return
    const change: PermissionCatalogChange = isStandard
      ? {
          type: "SET_ALLOW_SAME_LEVEL",
          model_key: model.key,
          allow_same_level: allowSameLevel,
        }
      : createMode
        ? {
            type: "CREATE_MODEL",
            name: name.trim(),
            action_codes: selectedActionCodes(actions, selected),
            active,
            allow_same_level: canAllowSameLevel ? allowSameLevel : false,
          }
        : {
          type: "UPDATE_MODEL",
          model_key: model.key,
          name: name.trim(),
          action_codes: selectedActionCodes(actions, selected),
          active,
          allow_same_level: canAllowSameLevel ? allowSameLevel : false,
          }

    setSaving(true)
    try {
      setDraft(await onCreateDraft([change]))
    } finally {
      setSaving(false)
    }
  }

  const handleApplyPreset = () => {
    // The blank option is the only way back to an empty selection: picking the
    // placeholder just disabled the button, so a model could gain actions from a
    // preset but never be cleared again.
    if (selectedPreset === BLANK_PRESET_KEY) {
      const blank = { key: BLANK_PRESET_KEY, name: t("model.preset.blank"), action_codes: [] }
      setSelected(new Set())
      setAllowSameLevel(false)
      setDraft(null)
      onInitializePreset?.(blank)
      return
    }
    const preset = presets.find((item) => item.key === selectedPreset)
    if (!preset) return
    const initializedPreset = {
      ...preset,
      action_codes: [...preset.action_codes],
    }
    setSelected(new Set(initializedPreset.action_codes))
    setAllowSameLevel(false)
    setDraft(null)
    onInitializePreset?.(initializedPreset)
  }

  const handleDelete = () => {
    if (disabled || saving || createMode || isStandard) return
    bsConfirm({
      desc: t("model.confirmDelete", { name: model.name }),
      okTxt: t("model.delete"),
      async onOk(next) {
        setSaving(true)
        setDeleteBlocked(false)
        try {
          const deleteDraft = await onDeleteModel(model.key)
          setDraft(deleteDraft)
          onReviewImpact(deleteDraft)
        } catch {
          setDeleteBlocked(true)
        } finally {
          setSaving(false)
          next()
        }
      },
    })
  }

  return (
    <section
      aria-label={t("model.title")}
      className="flex h-full min-h-0 flex-col rounded-xl border bg-background"
    >
      <div className="flex shrink-0 flex-wrap items-start justify-between gap-3 border-b p-5">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="truncate text-base font-semibold text-foreground">
              {createMode ? t("model.create") : name || model.name}
            </h2>
            <span className="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
              {t(`model.kind.${model.kind.toLowerCase()}`)}
            </span>
            {!createMode && !active && (
              <span className="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
                {t("model.inactive")}
              </span>
            )}
          </div>
          <p className="mt-1 text-sm leading-6 text-muted-foreground">
            {t("model.description")}
          </p>
        </div>
        {/* A bare "3" said nothing. The level is derived from the highest action
            in the selection, so name it and say where it came from. */}
        <div className="shrink-0 text-right">
          <p className="text-xs text-muted-foreground">
            {t("model.derivedLevel")}
          </p>
          <p
            data-testid="model-derived-level"
            // The visible text is localized ("Level 3"); the raw tier stays
            // readable here for anything asserting on the value itself.
            data-level={derivedLevel ?? "unassigned"}
            className="text-lg font-semibold tabular-nums text-foreground"
          >
            {derivedLevel === null || derivedLevel === undefined
              ? t("actionLevel.unassigned")
              : t("actionLevel.level", { level: derivedLevel })}
          </p>
        </div>
      </div>

      {/* Only the form scrolls, so the title and the save bar stay in place while
          the action list — the tall part — moves. */}
      <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto p-5">
        {!isStandard && (
          <div className="grid gap-2 sm:grid-cols-[1fr_auto]">
            <div className="text-sm font-medium text-foreground">
              <span className="mb-1 block">{t("model.preset.label")}</span>
              <Select
                value={selectedPreset}
                disabled={disabled}
                onValueChange={setSelectedPreset}
              >
                <SelectTrigger
                  aria-label={t("model.preset.label")}
                  className="w-full bg-background"
                >
                  <SelectValue placeholder={t("model.preset.select")} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={BLANK_PRESET_KEY}>
                    {t("model.preset.blank")}
                  </SelectItem>
                  {presets.map((preset) => (
                    <SelectItem key={preset.key} value={preset.key}>
                      {preset.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <Button
              type="button"
              variant="outline"
              className="self-end"
              disabled={disabled || !selectedPreset}
              onClick={handleApplyPreset}
            >
              {t("model.preset.apply")}
            </Button>
          </div>
        )}

        <label className="text-sm font-medium text-foreground">
          <span className="mb-1 block">{t("model.name")}</span>
          <Input
            aria-label={t("model.name")}
            value={name}
            disabled={disabled || isStandard}
            
            onChange={(event) => setName(event.target.value)}
          />
        </label>

        {/* Grouped by level, because the level is what the selection produces:
            ticking anything in the "level 3" group makes this a level-3 model.
            A flat list made the derived level in the header look arbitrary. */}
        <fieldset className="grid gap-3">
          <legend className="mb-1 text-sm font-medium text-foreground">
            {t("model.actions")}
          </legend>
          {actionGroups.map((group) => (
            <div key={group.key} className="rounded-lg border">
              <div className="flex items-center justify-between gap-2 border-b bg-muted/30 px-3 py-1.5">
                <span className="text-xs font-medium text-foreground">
                  {group.title}
                </span>
                <span className="text-xs tabular-nums text-muted-foreground">
                  {group.selectedCount}/{group.actions.length}
                </span>
              </div>
              <div className="divide-y">
                {group.actions.map((action) => {
                  const isChecked = selected.has(action.code)
                  const actionDisabled =
                    disabled || isStandard || (!action.active && !isChecked)
                  return (
                    <label
                      key={action.code}
                      className="flex items-center gap-3 px-3 py-2 text-sm has-[:disabled]:opacity-60"
                    >
                      <Checkbox
                        aria-label={`${t("model.action")}.${action.code}`}
                        checked={isChecked}
                        disabled={actionDisabled}
                        onCheckedChange={(checked) =>
                          handleActionChange(action.code, checked === true)
                        }
                      />
                      <span className="min-w-0 flex-1">
                        <span className="block font-medium text-foreground">
                          {actionLabel(t, action.code, action.name)}
                        </span>
                        <span className="block truncate text-xs text-muted-foreground">
                          {action.code}
                        </span>
                      </span>
                      {action.level === null ? (
                        <span className="text-xs text-destructive">
                          {t("actionLevel.unassigned")}
                        </span>
                      ) : !action.active && (
                        <span className="text-xs text-destructive">
                          {t("actionLevel.inactive")}
                        </span>
                      )}
                    </label>
                  )
                })}
              </div>
            </div>
          ))}
        </fieldset>

        {/* Both switches carry a consequence the label alone never conveyed —
            "allow same level" in particular decides whether a holder can hand
            out their own tier. */}
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="flex items-start justify-between gap-3 rounded-lg border p-3 text-sm">
            <span className="min-w-0">
              <span className="block font-medium text-foreground">
                {t("model.active")}
              </span>
              <span className="mt-0.5 block text-xs leading-5 text-muted-foreground">
                {t("model.activeHint")}
              </span>
            </span>
            <Switch
              aria-label={t("model.active")}
              checked={active}
              disabled={disabled || isStandard}
              onCheckedChange={setActive}
            />
          </label>
          <label className="flex items-start justify-between gap-3 rounded-lg border p-3 text-sm">
            <span className="min-w-0">
              <span className="block font-medium text-foreground">
                {t("model.allowSameLevel")}
              </span>
              <span className="mt-0.5 block text-xs leading-5 text-muted-foreground">
                {canAllowSameLevel
                  ? t("model.allowSameLevelHint")
                  : t("model.allowSameLevelUnavailable")}
              </span>
            </span>
            <Switch
              aria-label={t("model.allowSameLevel")}
              checked={allowSameLevel}
              disabled={disabled || !canAllowSameLevel}
              onCheckedChange={setAllowSameLevel}
            />
          </label>
        </div>
      </div>

      {/* The draft notice used to sit at the end of the scrolling form, so the
          button that publishes it was below the fold — the author saved and saw
          nothing happen. It belongs beside the button that produced it. */}
      <div className="flex shrink-0 flex-wrap items-center justify-end gap-2 border-t p-4">
        {draft && (
          <div
            className="mr-auto flex min-w-0 flex-1 items-center gap-2 rounded-lg border border-primary/30 bg-primary/5 px-3 py-1.5 text-sm text-foreground"
            role="status"
          >
            <ShieldAlert
              aria-hidden="true"
              className="size-4 shrink-0 text-primary"
            />
            <span className="min-w-0">
              {t("impact.unpublished")}
              {" · "}
              {t("impact.pending", {
                resources: draft.impact.resource_count,
                grants: draft.impact.grant_count,
              })}
            </span>
            <Button
              type="button"
              size="sm"
              className="ml-auto shrink-0"
              onClick={() => onReviewImpact(draft)}
            >
              {t("impact.publishChanges")}
            </Button>
          </div>
        )}
        {!isStandard && !createMode && (
          <div className="mr-auto flex min-w-0 items-center gap-2">
            <Button
              type="button"
              variant="outline"
              className="shrink-0 text-destructive"
              disabled={disabled || saving}
              onClick={handleDelete}
            >
              {t("model.delete")}
            </Button>
            <span
              className={deleteBlocked ? "text-xs text-destructive" : "text-xs text-muted-foreground"}
              role={deleteBlocked ? "alert" : undefined}
            >
              {deleteBlocked
                ? t("model.deleteBlocked")
                : t("model.deleteRequirement")}
            </span>
          </div>
        )}
        <Button
          type="button"
          
          disabled={
            disabled ||
            saving ||
            (!isStandard &&
              (name.trim().length === 0 ||
                effectiveSelectedActions.length === 0 ||
                hasInvalidSelection))
          }
          onClick={() => void handleSave()}
        >
          {saving ? t("model.saving") : t("model.save")}
        </Button>
      </div>
    </section>
  )
}
