import { locationContext } from "@/contexts/locationContext";
import { FIXED_ROLE_VALUES, selectableRoleValues } from "./approverSources";
import { Button, Input, Select } from '@bisheng/ui';
import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";

import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";

import { type ApprovalFlowItem, type ApprovalRouteItem } from "@/controllers/API/approval";
import { getRolesApi } from "@/controllers/API/user";
import { useContext, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { CONDITION_FIELD_META, normalizeApprovalRoles } from "./approvalMetadata";

interface RouteDialogProps {
  open: boolean;
  initial: Partial<ApprovalRouteItem>;
  flows: ApprovalFlowItem[];
  conditionFields: string[];
  allowPassRoute?: boolean;
  onClose: () => void;
  onConfirm: (data: {
    route_name: string;
    route_type: string;
    flow_definition_id: number | null;
    match_config: { field?: string; value?: string };
  }) => void;
}

export function RouteDialog({ open, initial, flows, conditionFields, allowPassRoute = true, onClose, onConfirm }: RouteDialogProps) {
  const [name, setName] = useState(initial.route_name ?? "");
  const [type, setType] = useState(!allowPassRoute && initial.route_type === "pass" ? "flow" : (initial.route_type ?? "flow"));
  const [flowId, setFlowId] = useState(initial.flow_definition_id ? String(initial.flow_definition_id) : "");
  const [condField, setCondField] = useState(initial.match_config?.field ?? "");
  const [condValue, setCondValue] = useState(initial.match_config?.value ?? "");
  const [systemRoles, setSystemRoles] = useState<{ value: string; label: string }[]>([]);

  const dialogSnapshot = useRef({ initial, allowPassRoute });
  dialogSnapshot.current = { initial, allowPassRoute };
  useEffect(() => {
    if (open) {
      const { initial, allowPassRoute } = dialogSnapshot.current;
      setName(initial.route_name ?? "");
      setType(!allowPassRoute && initial.route_type === "pass" ? "flow" : (initial.route_type ?? "flow"));
      setFlowId(initial.flow_definition_id ? String(initial.flow_definition_id) : "");
      setCondField(initial.match_config?.field ?? "");
      setCondValue(initial.match_config?.value ?? "");
      // Load system roles for applicant_role condition values
      getRolesApi("")
        .then((res) => {
          const list = normalizeApprovalRoles(res);
          setSystemRoles(
            list.map((r) => ({
              value: `role_${r.id}`,
              label: r.role_name,
            })),
          );
        })
        .catch(() => setSystemRoles([]));
    }
  }, [open]);

  const { t } = useTranslation("bs");
  const selectLabels = useSelectLabels();
  const { appConfig } = useContext(locationContext);
  const roleValueOptions = useMemo(() => {
    const selectable = selectableRoleValues(!!appConfig.multiTenantEnabled);
    return [...selectable, ...FIXED_ROLE_VALUES.filter(value => value.value === condValue && !selectable.some(option => option.value === value.value))];
  }, [appConfig.multiTenantEnabled, condValue]);
  const fieldMeta = condField ? CONDITION_FIELD_META[condField] : null;
  // For applicant_role: fixed entries use i18n keys → need t(); system roles have real names → no translation
  const allRoleValues =
    condField === "applicant_role"
      ? [
          ...roleValueOptions.map((v) => ({ value: v.value, label: t(v.label, { defaultValue: v.value }) })),
          ...systemRoles, // label is already the display name, skip t()
        ]
      : (fieldMeta?.values ?? []).map((v) => ({
          value: v.value,
          label: t(v.label, { defaultValue: v.value }),
        }));
  const hasEnumValues = allRoleValues.length > 0;

  const handleFieldChange = (f: string) => {
    setCondField(f);
    setCondValue(""); // reset value when field changes
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{initial.id ? t("approvalPage.editRoute") : t("approvalPage.addRoute")}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <label className="block text-sm text-muted-foreground">
            {t("approvalPage.routeNameLabel")}
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder={t("subjectSearch.routeExample")} className={"mt-1 block w-full"} />
          </label>

          {/* Condition */}
          <div className="rounded-lg border border-border bg-gray-50 dark:bg-gray-50/[0.06] p-3 space-y-3">
            <div className="text-xs font-medium text-muted-foreground">{t("approvalPage.matchConditionHint")}</div>
            <div className="flex items-center gap-2">
              <Select {...selectLabels} aria-label={t("approvalPage.matchConditionHint")} value={condField || '__none__'} className="min-w-0 flex-1"
                options={[{ value: '__none__', label: t("approvalPage.noCondition") }, ...conditionFields.filter(Boolean).map(field => ({ value: field, label: CONDITION_FIELD_META[field] ? t(CONDITION_FIELD_META[field].label, { defaultValue: field }) : field }))]}
                onChange={value => handleFieldChange(value === '__none__' ? '' : String(value ?? ''))} />
              {condField && (
                <>
                  <span className="text-xs text-muted-foreground">=</span>
                  {hasEnumValues ? (
                    condField === "applicant_role" ? (
                      // Searchable dropdown for applicant_role (may have many system roles)
                      <div className="flex-1">
                        <Select
                          {...selectLabels}
                          showSearch
                          className="w-full"
                          aria-label={fieldMeta ? t(fieldMeta.label, { defaultValue: condField }) : condField}
                          value={condValue || null}
                          options={allRoleValues.filter((v) => v.value != null && v.value !== "")}
                          placeholder={t("approvalPage.pleaseSelect")}
                          onChange={(v) => setCondValue(v == null ? "" : String(v))}
                        />
                      </div>
                    ) : (
                      <Select {...selectLabels} aria-label={fieldMeta ? t(fieldMeta.label, { defaultValue: condField }) : condField}
                        value={condValue || null} className="min-w-0 flex-1" allowClear
                        placeholder={t("approvalPage.pleaseSelect")} options={allRoleValues.filter(v => v.value != null && v.value !== '')}
                        onChange={value => setCondValue(String(value ?? ''))} />
                    )
                  ) : (
                    <Input value={condValue} onChange={(e) => setCondValue(e.target.value)} placeholder={t("approvalPage.inputConditionValue")} />
                  )}
                </>
              )}
            </div>
            {condField && !condValue && (
              <p className="text-xs text-amber-500 dark:text-amber-400">{t("approvalPage.conditionValueWarning")}</p>
            )}
          </div>

          {/* Route type */}
          <label className="block text-sm text-muted-foreground">
            {t("approvalPage.routeTypeLabel")}
            <Select {...selectLabels} aria-label={t("approvalPage.routeTypeLabel")} value={type} className="mt-1"
              options={[...(allowPassRoute ? [{ value: 'pass', label: t("approvalPage.routeTypePassFull") }] : []), { value: 'flow', label: t("approvalPage.routeTypeFlowFull") }]}
              onChange={value => setType(String(value ?? 'flow'))} />
          </label>
          {!allowPassRoute && <p className="text-xs text-muted-foreground">{t("approvalPage.routeTypeMandatoryHint")}</p>}
          {type === "flow" && (
            <label className="block text-sm text-muted-foreground">
              {t("approvalPage.bindFlow")}
              <Select {...selectLabels} aria-label={t("approvalPage.bindFlow")} value={flowId || null} className="mt-1" allowClear
                status={!flowId ? 'error' : 'default'} placeholder={t("approvalPage.selectFlow")}
                options={flows.filter(flow => flow.id != null).map(flow => ({ value: String(flow.id), label: flow.flow_name || flow.flow_code || '' }))}
                onChange={value => setFlowId(String(value ?? ''))} />
              {!flowId && (
                <p className="mt-1 text-xs text-red-500 dark:text-red-400">{t("approvalPage.flowRequiredHint")}</p>
              )}
            </label>
          )}
        </div>
        <DialogFooter>
          <Button size="medium" variant="outlined" type="button" onClick={onClose} color="default">
            {t("approvalPage.cancel")}
          </Button>
          <Button size="medium" variant="solid" type="button" disabled={!name.trim() || (type === "flow" && !flowId)} onClick={() =>
              onConfirm({
                route_name: name.trim(),
                route_type: type,
                flow_definition_id: type === "flow" && flowId ? Number(flowId) : null,
                match_config: condField ? { field: condField, value: condValue } : {},
              })
            } color="primary">
            {t("approvalPage.save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
