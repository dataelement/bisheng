import { Button } from "@/components/bs-ui/button";
import { getAuditMode, saveAuditMode } from "@/controllers/API/dshModelAudit";
import type { AuditMode, AuditModeSnapshot } from "@/types/dshModelAudit";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { DshChoice } from "./common";

interface ModelAuditModeProps {
  tenantId?: number;
  canConfigure: boolean;
}
export function ModelAuditMode({
  tenantId,
  canConfigure,
}: ModelAuditModeProps) {
  const { t } = useTranslation();
  const [snapshot, setSnapshot] = useState<AuditModeSnapshot | null>(null);
  const [selected, setSelected] = useState<AuditMode>("OFF");
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setSnapshot(null);
    setFailed(false);
    getAuditMode(tenantId, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) {
          setSnapshot(value);
          setSelected(value.mode);
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      });
    return () => controller.abort();
  }, [tenantId, revision]);
  const handleSave = async () => {
    if (!tenantId || !snapshot) return;
    setBusy(true);
    setFailed(false);
    try {
      setSnapshot(await saveAuditMode(tenantId, snapshot, selected));
    } catch {
      setFailed(true);
      setRevision((old) => old + 1);
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="space-y-3 rounded-lg border p-4">
      <h3 className="font-medium">{t("dsh.modelAuditView.mode")}</h3>
      <p className="text-sm text-muted-foreground">
        {t("dsh.modelAuditView.modeHint")}
      </p>
      <div className="flex flex-wrap gap-2">
        <DshChoice
          label={t("dsh.modelAuditView.mode")}
          value={selected}
          options={(["OFF", "METADATA", "CONTENT"] as const).map((value) => ({
            value,
            label: t("dsh.modelAuditView.modes." + value),
          }))}
          disabled={!canConfigure || !snapshot || busy}
          onChange={(value) => setSelected(value as AuditMode)}
        />
        {canConfigure && (
          <Button
            variant="outline"
            disabled={
              !tenantId || !snapshot || busy || selected === snapshot.mode
            }
            onClick={handleSave}
          >
            {t("dsh.save")}
          </Button>
        )}
        <Button
          variant="outline"
          disabled={busy}
          onClick={() => setRevision((old) => old + 1)}
        >
          {t("dsh.refresh")}
        </Button>
      </div>
      {failed && <p role="alert">{t("dsh.modelAuditView.loadError")}</p>}
      {!snapshot && !failed && <p role="status">{t("dsh.loading")}</p>}
    </section>
  );
}
