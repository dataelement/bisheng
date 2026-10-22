import { Button, Input, Select } from '@bisheng/ui';
import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";

import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";

import { type ApprovalFlowItem, type ApprovalRouteItem } from "@/controllers/API/approval";
import { getRolesApi } from "@/controllers/API/user";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { CONDITION_FIELD_META, FIXED_ROLE_VALUES, normalizeApprovalRoles } from "./approvalMetadata";

interface RouteDialogProps {
  open: boolean;
  initial: Partial<ApprovalRouteItem>;
  flows: ApprovalFlowItem[];
  conditionFields: string[];
  onClose: () => void;
  onConfirm: (data: {
    route_name: string;
    route_type: string;
    flow_definition_id: number | null;
    match_config: { field?: string; value?: string };
  }) => void;
}

export function RouteDialog({ open, initial, flows, conditionFields, onClose, onConfirm }: RouteDialogProps) {
  const [name, setName] = useState(initial.route_name ?? "");
  const [type, setType] = useState(initial.route_type ?? "flow");
  const [flowId, setFlowId] = useState(initial.flow_definition_id ? String(initial.flow_definition_id) : "");
  const [condField, setCondField] = useState(initial.match_config?.field ?? "");
  const [condValue, setCondValue] = useState(initial.match_config?.value ?? "");
  const [systemRoles, setSystemRoles] = useState<{ value: string; label: string }[]>([]);

  const dialogSnapshot = useRef({ initial });
  dialogSnapshot.current = { initial };
  useEffect(() => {
    if (open) {
      const { initial } = dialogSnapshot.current;
      setName(initial.route_name ?? "");
      setType(initial.route_type ?? "flow");
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
  const fieldMeta = condField ? CONDITION_FIELD_META[condField] : null;
  // For applicant_role: fixed entries use i18n keys → need t(); system roles have real names → no translation
  const allRoleValues =
    condField === "applicant_role"
      ? [
          ...FIXED_ROLE_VALUES.map((v) => ({ value: v.value, label: t(v.label, { defaultValue: v.value }) })),
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
              <select
                value={condField}
                onChange={(e) => handleFieldChange(e.target.value)}
                className="h-9 flex-1 rounded-lg border border-border bg-background px-2 text-sm text-foreground outline-none"
              >
                <option value="">{t("approvalPage.noCondition")}</option>
                {conditionFields.map((f) => (
                  <option key={f} value={f}>
                    {CONDITION_FIELD_META[f] ? t(CONDITION_FIELD_META[f].label, { defaultValue: f }) : f}
                  </option>
                ))}
              </select>
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
                      <select
                        value={condValue}
                        onChange={(e) => setCondValue(e.target.value)}
                        className="h-9 flex-1 rounded-lg border border-border bg-background px-2 text-sm text-foreground outline-none"
                      >
                        <option value="">{t("approvalPage.pleaseSelect")}</option>
                        {allRoleValues.map((v) => (
                          <option key={v.value} value={v.value}>
                            {v.label}
                          </option>
                        ))}
                      </select>
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
            <select
              value={type}
              onChange={(e) => setType(e.target.value)}
              className="mt-1 block h-10 w-full rounded-lg border border-border bg-background px-3 text-sm text-foreground outline-none"
            >
              <option value="pass">{t("approvalPage.routeTypePassFull")}</option>
              <option value="flow">{t("approvalPage.routeTypeFlowFull")}</option>
            </select>
          </label>
          {type === "flow" && (
            <label className="block text-sm text-muted-foreground">
              {t("approvalPage.bindFlow")}
              <select
                value={flowId}
                onChange={(e) => setFlowId(e.target.value)}
                className={`mt-1 block h-10 w-full rounded-lg border bg-background px-3 text-sm text-foreground outline-none ${!flowId ? "border-red-400 dark:border-red-500/60" : "border-border"}`}
              >
                <option value="">{t("approvalPage.selectFlow")}</option>
                {flows.map((f) => (
                  <option key={f.id} value={String(f.id)}>
                    {f.flow_name || f.flow_code}
                  </option>
                ))}
              </select>
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
