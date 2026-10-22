import { Button } from '@bisheng/ui';

import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { type ApprovalScenarioPreset } from "@/controllers/API/approval";
import { useContext, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { approverSourceLabel } from "./approverSources";
import { locationContext } from "@/contexts/locationContext";

interface AddScenarioDialogProps {
  open: boolean;
  presets: ApprovalScenarioPreset[];
  existingCodes: Set<string>;
  onClose: () => void;
  onConfirm: (preset: ApprovalScenarioPreset) => void;
}

export function AddScenarioDialog({ open, presets, existingCodes, onClose, onConfirm }: AddScenarioDialogProps) {
  const { t } = useTranslation("bs");
  const { appConfig } = useContext(locationContext);
  const available = useMemo(() => presets.filter((p) => !existingCodes.has(p.scenario_code)), [presets, existingCodes]);
  const [selected, setSelected] = useState("");
  useEffect(() => {
    if (open) setSelected(available[0]?.scenario_code ?? "");
  }, [open, available]);

  const preset = available.find((p) => p.scenario_code === selected) ?? null;

  const conditionFieldLabels = (preset?.condition_fields ?? [])
    .map((f) => t(`approvalPage.condition.${f}`, { defaultValue: f }))
    .join("、");

  const approverSourceLabels = (preset?.approver_source_types ?? [])
    .map((s) => approverSourceLabel(s, t, undefined, !!appConfig.multiTenantEnabled))
    .join("、");

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{t("approvalPage.addScenarioTitle")}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <label className="block text-sm text-muted-foreground">
            {t("approvalPage.scenarioNameLabel")}
            <select
              value={selected}
              onChange={(e) => setSelected(e.target.value)}
              className="mt-1 block h-10 w-full rounded-lg border border-border bg-background px-3 text-sm text-foreground outline-none"
            >
              {available.length === 0 && <option value="">{t("approvalPage.allPresetsAdded")}</option>}
              {available.map((p) => (
                <option key={p.scenario_code} value={p.scenario_code}>
                  {p.scenario_name}
                </option>
              ))}
            </select>
          </label>
          {preset && (
            <div className="rounded-lg bg-gray-50 dark:bg-gray-50/[0.06] p-3 text-xs text-muted-foreground space-y-1.5">
              {conditionFieldLabels && (
                <div>
                  <span className="font-medium text-foreground">{t("approvalPage.conditionLabel")}：</span>
                  {conditionFieldLabels}
                </div>
              )}
              {approverSourceLabels && (
                <div>
                  <span className="font-medium text-foreground">{t("approvalPage.approverSourceLabel")}：</span>
                  {approverSourceLabels}
                </div>
              )}
            </div>
          )}
        </div>
        <DialogFooter>
          <Button size="medium" variant="outlined" type="button" onClick={onClose} color="default">
            {t("cancel")}
          </Button>
          <Button size="medium" variant="solid" type="button" disabled={!preset} onClick={() => preset && onConfirm(preset)} color="primary">
            {t("approvalPage.confirmAdd")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
