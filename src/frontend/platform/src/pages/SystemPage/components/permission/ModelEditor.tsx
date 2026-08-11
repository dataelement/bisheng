import { Button } from "@/components/bs-ui/button"
import { Checkbox } from "@/components/bs-ui/checkBox"
import { Input } from "@/components/bs-ui/input"
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

  const handleDelete = async () => {
    if (disabled || saving || createMode || isStandard || active) return
    setSaving(true)
    try {
      setDraft(await onCreateDraft([
        {
          type: "DELETE_MODEL",
          model_key: model.key,
        },
      ]))
    } finally {
      setSaving(false)
    }
  }

  return (
    <section
      aria-label={t("model.title")}
      className="flex min-h-0 flex-col gap-5 rounded-xl border bg-background p-5"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-foreground">
            {t("model.title")}
          </h2>
          <p className="mt-1 text-sm leading-6 text-muted-foreground">
            {t(`model.kind.${model.kind.toLowerCase()}`)}
          </p>
        </div>
        <span
          data-testid="model-derived-level"
          className="rounded-full bg-muted px-3 py-1 text-sm font-medium text-foreground"
        >
          {derivedLevel ?? t("actionLevel.unassigned")}
        </span>
      </div>

      {presets.length > 0 && !isStandard && (
        <div className="grid gap-2 sm:grid-cols-[1fr_auto]">
          <label className="text-sm font-medium text-foreground">
            <span className="mb-1 block">{t("model.preset.label")}</span>
            <select
              aria-label={t("model.preset.label")}
              value={selectedPreset}
              disabled={disabled}
              onChange={(event) => setSelectedPreset(event.target.value)}
              className="min-h-11 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <option value="">{t("model.preset.select")}</option>
              {presets.map((preset) => (
                <option key={preset.key} value={preset.key}>
                  {preset.name}
                </option>
              ))}
            </select>
          </label>
          <Button
            type="button"
            variant="outline"
            className="min-h-11 self-end"
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
          className="min-h-11"
          onChange={(event) => setName(event.target.value)}
        />
      </label>

      <fieldset className="grid gap-2">
        <legend className="mb-1 text-sm font-medium text-foreground">
          {t("model.actions")}
        </legend>
        {eligibleActions.map((action) => {
          const isChecked = selected.has(action.code)
          const actionDisabled =
            disabled || isStandard || (!action.active && !isChecked)
          return (
            <label
              key={action.code}
              className="flex min-h-11 items-center gap-3 rounded-lg border px-3 py-2 text-sm"
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
                  {action.name}
                </span>
                <span className="block truncate text-xs text-muted-foreground">
                  {action.code}
                </span>
              </span>
              {action.level === null ? (
                <span className="text-xs font-medium text-amber-700">
                  {t("actionLevel.unassigned")}
                </span>
              ) : !action.active && (
                <span className="text-xs font-medium text-red-700">
                  {t("actionLevel.inactive")}
                </span>
              )}
            </label>
          )
        })}
      </fieldset>

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="flex min-h-11 items-center justify-between gap-3 rounded-lg border px-3 text-sm font-medium">
          <span>{t("model.active")}</span>
          <Switch
            aria-label={t("model.active")}
            checked={active}
            disabled={disabled || isStandard}
            onCheckedChange={setActive}
          />
        </label>
        <label className="flex min-h-11 items-center justify-between gap-3 rounded-lg border px-3 text-sm font-medium">
          <span>{t("model.allowSameLevel")}</span>
          <Switch
            aria-label={t("model.allowSameLevel")}
            checked={allowSameLevel}
            disabled={disabled || !canAllowSameLevel}
            onCheckedChange={setAllowSameLevel}
          />
        </label>
      </div>

      {draft && (
        <div
          className="flex items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-900"
          role="status"
        >
          <ShieldAlert aria-hidden="true" className="size-4 shrink-0" />
          <span className="flex-1">
            {t("impact.pending", {
              resources: draft.impact.resource_count,
              grants: draft.impact.grant_count,
            })}
          </span>
          <Button
            type="button"
            variant="outline"
            className="min-h-11 bg-background"
            onClick={() => onReviewImpact(draft)}
          >
            {t("impact.review")}
          </Button>
        </div>
      )}

      <div className="flex flex-wrap justify-end gap-2">
        {!isStandard && !createMode && (
          <Button
            type="button"
            variant="outline"
            className="min-h-11 text-red-700"
            disabled={disabled || saving || active}
            onClick={() => void handleDelete()}
          >
            {t("model.delete")}
          </Button>
        )}
        <Button
          type="button"
          className="min-h-11"
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
