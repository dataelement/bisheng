import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Table, TableBody, TableHead, TableHeader, TableRow } from "@/components/bs-ui/table";
import type {
  PermissionActionLevel,
  PermissionCatalogAction,
  PermissionCatalogChange,
  PermissionCatalogDraft,
  PermissionCatalogModel,
  PermissionCatalogRelease,
} from "@/controllers/API/permission";
import { cn } from "@/utils";
import { Button, Checkbox, Input, Switch, Tag, Tooltip, TooltipProvider, toast } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { actionLabel } from "./actionLabels";

const NEW_MODEL: PermissionCatalogModel = {
  key: "__new_custom_model__",
  name: "",
  kind: "CUSTOM",
  config_scope: "PLATFORM",
  derived_level: null,
  active: true,
  allow_same_level: false,
  action_codes: [],
  version: 0,
};

const RISK_COLORS = { 1: "default", 2: "success", 3: "warning", 4: "danger" } as const;
const COLUMN_WIDTHS = { name: 112, risk: 120, active: 80, grant: 96 };
const PERMISSION_COLUMN_WIDTH = 80;
const NAME_COLUMN = "xl:sticky xl:left-0";
const RISK_COLUMN = "xl:sticky xl:left-[var(--permission-risk-left)]";
const ACTIVE_COLUMN = "xl:sticky xl:right-[var(--permission-active-right)]";
const GRANT_COLUMN = "xl:sticky xl:right-[var(--permission-grant-right)]";
const OPERATIONS_COLUMN = "xl:sticky xl:right-0";
const HEADER_CELL = "sticky top-0 z-[2] border-b border-border-base bg-fill-1 px-2 text-center text-body font-medium text-text-1";
const ROW_CELL = "h-14 px-2 align-middle";
const GROUP_DIVIDER = "border-l border-border-base";
// On the pinned left edge, paint on the same side as the moving separators.
const LEFT_EDGE_DIVIDER = "border-r border-border-base xl:border-r-0 xl:after:pointer-events-none xl:after:absolute xl:after:inset-y-0 xl:after:left-full xl:after:w-px xl:after:bg-border-base";
const TOOLTIP_CONTROL = "inline-flex align-middle [&>button:disabled]:pointer-events-none";

interface ModelForm {
  model: PermissionCatalogModel;
  name: string;
  active: boolean;
  allowSameLevel: boolean;
  selected: Set<string>;
  creating: boolean;
}

interface ModelCatalogPanelProps {
  catalog: PermissionCatalogRelease;
  headerTarget?: HTMLDivElement | null;
  onConfigureRisk?: () => void;
  onCreateDraft: (changes: PermissionCatalogChange[]) => Promise<PermissionCatalogDraft>;
  onDeleteModel: (modelKey: string) => Promise<PermissionCatalogDraft>;
  onReviewImpact: (draft: PermissionCatalogDraft, variant?: "modelEdit") => void;
}

function createModelForm(model: PermissionCatalogModel): ModelForm {
  return {
    model,
    name: model.name,
    active: model.active,
    allowSameLevel: model.allow_same_level,
    selected: new Set(model.action_codes),
    creating: model.key === NEW_MODEL.key,
  };
}

function canGrantSameLevel(actions: PermissionCatalogAction[], selected: Set<string>) {
  return selected.has("manage_permission") && actions.some(
    (action) => action.code === "manage_permission" && action.active && action.level !== null,
  );
}

interface RiskTagProps {
  level: PermissionActionLevel | null;
}

function RiskTag({ level }: RiskTagProps) {
  const { t } = useTranslation("permission");
  return (
    <span data-testid="model-derived-level" data-level={level ?? "unassigned"}>
      <Tag size="small" color={level === null ? "default" : RISK_COLORS[level]}>
        {level === null ? t("model.noRiskLevel") : t(`actionLevel.riskLevels.${level}`)}
      </Tag>
    </span>
  );
}

export function ModelCatalogPanel({
  catalog,
  headerTarget,
  onConfigureRisk,
  onCreateDraft,
  onDeleteModel,
  onReviewImpact,
}: ModelCatalogPanelProps) {
  const { t, i18n } = useTranslation("permission");
  const [editing, setEditing] = useState<ModelForm | null>(null);
  const [saving, setSaving] = useState(false);
  const newRowRef = useRef<HTMLTableRowElement>(null);
  const newNameRef = useRef<HTMLInputElement>(null);
  const creating = editing?.creating === true;
  // Keep the column stable across row states while allowing room for the localized buttons and spinner.
  const operationsWidth = (i18n.resolvedLanguage ?? i18n.language) === "zh-Hans" ? 128 : 176;
  const scrollShadows = {
    pinnedLeft: COLUMN_WIDTHS.name + COLUMN_WIDTHS.risk,
    pinnedRight: COLUMN_WIDTHS.active + COLUMN_WIDTHS.grant + operationsWidth,
  };
  const stickyOffsets = {
    "--permission-risk-left": `${COLUMN_WIDTHS.name}px`,
    "--permission-active-right": `${COLUMN_WIDTHS.grant + operationsWidth}px`,
    "--permission-grant-right": `${operationsWidth}px`,
  };

  useLayoutEffect(() => {
    if (!creating) return;
    newRowRef.current?.scrollIntoView?.({ block: "center", inline: "nearest" });
    newNameRef.current?.focus({ preventScroll: true });
  }, [creating]);

  const actions = useMemo(
    () => [...catalog.actions].sort((left, right) => left.sort_order - right.sort_order),
    [catalog.actions],
  );
  const actionGroups = useMemo(() => {
    const groupLevels = [1, 2, 3, 4, null] as const;
    const assignedCodes = new Set(catalog.models.flatMap((model) => model.action_codes));
    return groupLevels
      .flatMap((level) => {
        const members = actions.filter((action) => (
          action.level === level && (level !== null || assignedCodes.has(action.code))
        ));
        return members.length ? [{ level, members }] : [];
      })
      .map((group, index) => ({ ...group, showDivider: index > 0 }));
  }, [actions, catalog.models]);
  const columns = actionGroups.flatMap(({ members, showDivider }) => (
    members.map((action, index) => ({ action, showDivider: showDivider && index === 0 }))
  ));
  const columnCount = Math.max(1, columns.length) + 5;
  const headerRowCount = columns.length > 0 ? 2 : 1;

  const isStandard = editing?.model.kind === "STANDARD";
  const actionsChanged = Boolean(editing && (
    editing.selected.size !== editing.model.action_codes.length
    || editing.model.action_codes.some((code) => !editing.selected.has(code))
  ));
  const hasUnsavedChanges = Boolean(editing && (
    editing.name !== editing.model.name
    || editing.active !== editing.model.active
    || editing.allowSameLevel !== editing.model.allow_same_level
    || actionsChanged
  ));
  const selectedActions = actions.filter((action) => editing?.selected.has(action.code));
  const effectiveActions = selectedActions.filter((action) => action.active && action.level !== null);
  const hasInvalidSelection = Boolean(editing && effectiveActions.length !== editing.selected.size);
  const derivedLevel = isStandard && !actionsChanged
    ? editing.model.derived_level
    : effectiveActions.reduce<PermissionActionLevel | null>(
      (level, action) => (action.level !== null && action.level > (level ?? 0) ? action.level : level),
      null,
    );
  const canConfirm = Boolean(editing && (isStandard || (
    editing.name.trim() && effectiveActions.length > 0 && !hasInvalidSelection
  )));
  // The catalog API currently accepts only same-level granting changes for built-in templates.
  const canSave = canConfirm && !(isStandard && actionsChanged);

  const handleCloseEditor = () => {
    setEditing(null);
  };

  const handleCancelEditing = () => {
    if (saving) return;
    if (!hasUnsavedChanges) {
      handleCloseEditor();
      return;
    }

    bsConfirm({
      title: t("model.unsavedTitle"),
      desc: t("model.discardUnsavedDescription"),
      canelTxt: t("organization.keepEditing", { ns: "bs" }),
      okTxt: t("model.discard"),
      variant: "default",
      onOk: (close) => {
        handleCloseEditor();
        close();
      },
    });
  };

  const handleSave = async (closePrompt?: () => void) => {
    if (!editing || !canSave || saving) return;
    const change: PermissionCatalogChange = isStandard
      ? {
        type: "SET_ALLOW_SAME_LEVEL",
        model_key: editing.model.key,
        allow_same_level: editing.allowSameLevel,
      }
      : {
        type: editing.creating ? "CREATE_MODEL" : "UPDATE_MODEL",
        ...(!editing.creating && { model_key: editing.model.key }),
        name: editing.name.trim(),
        action_codes: effectiveActions.map((action) => action.code),
        active: editing.active,
        allow_same_level: canGrantSameLevel(actions, editing.selected) && editing.allowSameLevel,
      };

    setSaving(true);
    try {
      const draft = await onCreateDraft([change]);
      closePrompt?.();
      onReviewImpact(draft, editing.creating ? undefined : "modelEdit");
    } catch {
      toast.show({ type: "error", message: t("model.saveFailed") });
    } finally {
      setSaving(false);
    }
  };

  const handleRowIntent = (next: () => void) => {
    if (saving) return;
    if (!creating && !hasUnsavedChanges) {
      handleCloseEditor();
      next();
      return;
    }

    bsConfirm({
      title: t("model.unsavedTitle"),
      desc: t(canSave ? "model.unsavedDescription" : "model.discardUnsavedDescription"),
      canelTxt: canSave ? t("model.discard") : t("impact.cancel"),
      okTxt: canSave ? t("model.saveDraft") : t("model.discard"),
      variant: "default",
      onCancel: canSave ? () => {
        handleCloseEditor();
        next();
      } : undefined,
      onOk: (close) => {
        if (canSave) return handleSave(close);
        close();
        handleCloseEditor();
        next();
      },
    });
  };

  const handleActionChange = (actionCode: string, checked: boolean) => {
    setEditing((current) => {
      if (!current) return current;
      const selected = new Set(current.selected);
      if (checked) selected.add(actionCode);
      else selected.delete(actionCode);
      return {
        ...current,
        selected,
        allowSameLevel: current.allowSameLevel
          && (current.model.kind === "STANDARD" || canGrantSameLevel(actions, selected)),
      };
    });
  };

  const handleDelete = (model: PermissionCatalogModel) => {
    bsConfirm({
      title: t("model.confirmDeleteTitle", { name: model.name }),
      desc: t("model.confirmDeleteDescription"),
      canelTxt: t("system.deleteConfirmation.cancel", { ns: "bs" }),
      okTxt: t("system.deleteConfirmation.confirm", { ns: "bs" }),
      async onOk(close) {
        setSaving(true);
        try {
          const draft = await onDeleteModel(model.key);
          close();
          onReviewImpact(draft);
        } catch {
          // The catalog owner reports the specific deletion blocker.
          close();
        } finally {
          setSaving(false);
        }
      },
    });
  };

  const renderModelRow = (model: PermissionCatalogModel, index: number) => {
    const form = editing?.model.key === model.key ? editing : null;
    const isBuiltin = model.kind === "STANDARD";
    const checkedActions = form?.selected ?? new Set(model.action_codes);
    const canGrant = canGrantSameLevel(actions, checkedActions);
    const rowBackground = index % 2 === 0 ? "bg-bg-page" : "bg-fill-1";
    const visibleName = isBuiltin && ["viewer", "editor", "manager", "owner"].includes(model.key)
      ? t(`level.${model.key}`, { defaultValue: model.name })
      : model.name;

    return (
      <TableRow
        key={model.key}
        ref={form?.creating ? newRowRef : undefined}
        data-testid={`permission-model-${model.key}`}
        hoverable={false}
        className={rowBackground}
      >
        <th scope="row" className={cn(ROW_CELL, NAME_COLUMN, "z-[1] text-left font-normal", rowBackground)}>
          {form && !isBuiltin ? (
            <Input
              ref={form.creating ? newNameRef : undefined}
              size="small"
              aria-label={t("model.name")}
              placeholder={t("model.name")}
              value={form.name}
              disabled={saving}
              onChange={(event) => setEditing({ ...form, name: event.target.value })}
            />
          ) : <span className="break-words font-medium">{visibleName}</span>}
        </th>
        <td className={cn(ROW_CELL, RISK_COLUMN, LEFT_EDGE_DIVIDER, "z-[1] text-center", rowBackground)}>
          <RiskTag level={form ? derivedLevel : model.derived_level} />
        </td>
        {columns.map(({ action, showDivider }) => {
          const checked = checkedActions.has(action.code);
          return (
            <td key={action.code} className={cn(ROW_CELL, "text-center", showDivider && GROUP_DIVIDER)}>
              {(form || checked) && (
                <Tooltip content={actionLabel(t, action.code, action.name)}>
                  <span className={TOOLTIP_CONTROL}>
                    <Checkbox
                      aria-label={`${t("model.action")}.${action.code}`}
                      size="medium"
                      checked={checked}
                      disabled={!form || saving || (!checked && (!action.active || action.level === null))}
                      onCheckedChange={form ? (value) => handleActionChange(action.code, value === true) : undefined}
                    />
                  </span>
                </Tooltip>
              )}
            </td>
          );
        })}
        {columns.length === 0 && <td aria-hidden />}
        <td className={cn(ROW_CELL, ACTIVE_COLUMN, GROUP_DIVIDER, "z-[1] text-center", rowBackground)}>
          <Switch
            size="small"
            checked={form?.active ?? model.active}
            disabled={saving || isBuiltin}
            aria-label={form ? t("model.active") : t("model.activeFor", { name: visibleName })}
            onCheckedChange={(active) => {
              if (form) setEditing({ ...form, active });
              else handleRowIntent(() => setEditing({ ...createModelForm(model), active }));
            }}
          />
        </td>
        <td className={cn(ROW_CELL, GRANT_COLUMN, "z-[1] text-center", rowBackground)}>
          <Tooltip content={t(canGrant ? "model.allowSameLevelHint" : "model.allowSameLevelUnavailable")}>
            <span className={TOOLTIP_CONTROL}>
              <Switch
                size="small"
                checked={form?.allowSameLevel ?? model.allow_same_level}
                disabled={saving || !canGrant}
                aria-label={form ? t("model.allowSameLevel") : t("model.allowSameLevelFor", { name: visibleName })}
                onCheckedChange={(allowSameLevel) => {
                  if (form) setEditing({ ...form, allowSameLevel });
                  else handleRowIntent(() => setEditing({ ...createModelForm(model), allowSameLevel }));
                }}
              />
            </span>
          </Tooltip>
        </td>
        <td className={cn(ROW_CELL, OPERATIONS_COLUMN, "z-[1] whitespace-nowrap", rowBackground)}>
          <div className="flex items-center justify-end gap-1">
            {form ? (
              <>
                <Button size="small" variant="text" color="default" disabled={saving} onClick={handleCancelEditing}>
                  {t("impact.cancel")}
                </Button>
                <Button size="small" loading={saving} disabled={!canConfirm} onClick={() => void handleSave()}>
                  {t("confirm", { ns: "bs" })}
                </Button>
              </>
            ) : (
              <>
                <Tooltip content={t("model.editRow")}>
                  <Button
                    type="button" size="small" variant="text" color="default" iconOnly
                    aria-label={t("model.editNamed", { name: visibleName })}
                    disabled={saving}
                    onClick={() => handleRowIntent(() => setEditing(createModelForm(model)))}
                  >
                    <Outlined.Edit aria-hidden />
                  </Button>
                </Tooltip>
                <span aria-hidden className="h-2 w-px shrink-0 bg-border-base" />
                <Tooltip content={t("model.copyRow")}>
                  <Button
                    type="button" size="small" variant="text" color="default" iconOnly
                    aria-label={t("model.copyNamed", { name: visibleName })}
                    disabled={saving}
                    onClick={() => handleRowIntent(() => setEditing(createModelForm({
                      ...NEW_MODEL,
                      action_codes: model.action_codes,
                      active: model.active,
                      allow_same_level: model.allow_same_level,
                    })))}
                  >
                    <Outlined.Copy aria-hidden />
                  </Button>
                </Tooltip>
                <span aria-hidden className="h-2 w-px shrink-0 bg-border-base" />
                <Tooltip content={t("model.deleteRow")}>
                  <Button
                    type="button" size="small" variant="text" color="danger" iconOnly
                    aria-label={t("model.deleteNamed", { name: visibleName })}
                    disabled={saving || isBuiltin}
                    onClick={() => handleRowIntent(() => handleDelete(model))}
                  >
                    <Outlined.Delete aria-hidden />
                  </Button>
                </Tooltip>
              </>
            )}
          </div>
          {form && !isBuiltin && hasInvalidSelection && (
            <span role="status" className="mt-1 block whitespace-normal text-right text-caption text-warning">
              {t("model.unavailableSelection")}
            </span>
          )}
        </td>
      </TableRow>
    );
  };

  const header = (
    <>
      <div className="flex flex-wrap items-center justify-end gap-3">
        {onConfigureRisk && (
          <Button type="button" variant="outlined" color="default" disabled={saving} onClick={() => handleRowIntent(onConfigureRisk)}>
            {t("actionLevel.configure")}
          </Button>
        )}
        <Button
          type="button"
          disabled={saving || creating}
          onClick={() => handleRowIntent(() => setEditing(createModelForm(NEW_MODEL)))}
        >
          {t("model.create")}
        </Button>
      </div>
      <p className="text-body text-text-2">{t("catalog.operationPermissionsDescription")}</p>
    </>
  );

  return (
    <section aria-label={t("model.title")} className="flex min-h-0 flex-1 flex-col gap-4">
      {headerTarget ? createPortal(header, headerTarget) : headerTarget === undefined ? header : null}
      <TooltipProvider>
        <Table
          aria-label={t("model.title")}
          className="table-fixed border-spacing-0 text-text-1"
          containerClassName="min-h-0 rounded-lg border border-border-base"
          scrollShadows={scrollShadows}
          style={{ ...stickyOffsets, minWidth: scrollShadows.pinnedLeft + scrollShadows.pinnedRight + Math.max(columns.length, 1) * PERMISSION_COLUMN_WIDTH }}
        >
          <colgroup>
            <col style={{ width: COLUMN_WIDTHS.name }} />
            <col style={{ width: COLUMN_WIDTHS.risk }} />
          </colgroup>
          {actionGroups.map(({ level, members }) => <colgroup key={level ?? "unassigned"} span={members.length} />)}
          {columns.length === 0 && <colgroup span={1} />}
          <colgroup>
            <col style={{ width: COLUMN_WIDTHS.active }} />
            <col style={{ width: COLUMN_WIDTHS.grant }} />
            <col style={{ width: operationsWidth }} />
          </colgroup>
          <TableHeader>
            <TableRow hoverable={false}>
              <TableHead scope="col" rowSpan={headerRowCount} className={cn(HEADER_CELL, NAME_COLUMN, "xl:z-[3] text-left")}>
                {t("model.name")}
              </TableHead>
              <TableHead scope="col" rowSpan={headerRowCount} aria-label={t("model.derivedLevel")} className={cn(HEADER_CELL, RISK_COLUMN, LEFT_EDGE_DIVIDER, "xl:z-[3]")}>
                <span className="inline-flex items-center gap-1">
                  <span>{t("model.derivedLevel")}</span>
                  <Tooltip content={t("model.riskHint")}>
                    <span role="img" aria-label={t("model.derivedLevel")} tabIndex={0} className="inline-flex shrink-0 rounded text-text-3 outline-none focus-visible:shadow-focus">
                      <Outlined.Question aria-hidden size={14} />
                    </span>
                  </Tooltip>
                </span>
              </TableHead>
              {actionGroups.map(({ level, members, showDivider }) => (
                <TableHead
                  key={level ?? "unassigned"} scope="colgroup" colSpan={members.length}
                  className={cn(HEADER_CELL, "h-9", showDivider && GROUP_DIVIDER)}
                >
                  <span className="text-caption text-text-2">
                    {level === null ? t("actionLevel.unassigned") : t(`actionLevel.riskLevels.${level}`)}
                  </span>
                </TableHead>
              ))}
              {columns.length === 0 && <TableHead rowSpan={headerRowCount} scope="col" className={HEADER_CELL}>{t("model.actions")}</TableHead>}
              <TableHead scope="col" rowSpan={headerRowCount} className={cn(HEADER_CELL, ACTIVE_COLUMN, GROUP_DIVIDER, "xl:z-[3]")}>
                {t("model.activeColumn")}
              </TableHead>
              <TableHead scope="col" rowSpan={headerRowCount} aria-label={t("model.allowSameLevel")} className={cn(HEADER_CELL, GRANT_COLUMN, "xl:z-[3]")}>
                <span className="inline-flex items-center gap-1">
                  <span>{t("model.allowSameLevel")}</span>
                  <Tooltip content={t("model.allowSameLevelHint")}>
                    <span role="img" aria-label={t("model.allowSameLevel")} tabIndex={0} className="inline-flex shrink-0 rounded text-text-3 outline-none focus-visible:shadow-focus">
                      <Outlined.Question aria-hidden size={14} />
                    </span>
                  </Tooltip>
                </span>
              </TableHead>
              <TableHead scope="col" rowSpan={headerRowCount} className={cn(HEADER_CELL, OPERATIONS_COLUMN, "xl:z-[3]")}>
                {t("model.operations")}
              </TableHead>
            </TableRow>
            {columns.length > 0 && (
              <TableRow hoverable={false}>
                {columns.map(({ action, showDivider }) => (
                  <TableHead key={action.code} scope="col" className={cn(HEADER_CELL, "top-9 h-9 px-1", showDivider && GROUP_DIVIDER)}>
                    <span className="text-body font-medium text-text-1">
                      {actionLabel(t, action.code, action.name)}
                    </span>
                  </TableHead>
                ))}
              </TableRow>
            )}
          </TableHeader>
          <TableBody>
            {catalog.models.map(renderModelRow)}
            {creating && renderModelRow(editing.model, catalog.models.length)}
            {catalog.models.length === 0 && !creating && (
              <TableRow hoverable={false}>
                <td colSpan={columnCount} className="py-10 text-center text-text-2">{t("model.empty")}</td>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </TooltipProvider>
    </section>
  );
}
