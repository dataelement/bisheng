import { Button } from "@/components/bs-ui/button";
import { getAuditMode, saveAuditMode } from "@/controllers/API/dshModelAudit";
import type { AuditMode, AuditModeSnapshot } from "@/types/dshModelAudit";
import { useEffect, useId, useState } from "react";
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
  const panelId = useId();
  const [open, setOpen] = useState(false);
  const [snapshot, setSnapshot] = useState<AuditModeSnapshot | null>(null);
  const [selected, setSelected] = useState<AuditMode>("OFF");
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const [saveFailed, setSaveFailed] = useState(false);
  const [revision, setRevision] = useState(0);
  const canCaptureContent = snapshot?.content_available === true;
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
    if (
      !canConfigure ||
      !tenantId ||
      !snapshot ||
      busy ||
      (selected === "CONTENT" && !canCaptureContent)
    )
      return;
    setBusy(true);
    setSaveFailed(false);
    try {
      const saved = await saveAuditMode(tenantId, snapshot, selected);
      setSnapshot(saved);
      setSelected(saved.mode);
    } catch {
      setSaveFailed(true);
      setRevision((old) => old + 1);
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <div
        className="flex flex-wrap items-center gap-2 text-sm md:justify-end"
        aria-describedby={`${panelId}-collection-hint`}
      >
        <span className="text-xs text-muted-foreground">
          {t("dsh.modelAuditView.capture_status")}
        </span>
        {snapshot && (
          <span className="inline-flex items-center gap-2">
            <i
              aria-hidden="true"
              className={
                "size-1.5 rounded-full " +
                (snapshot.mode === "OFF"
                  ? "bg-muted-foreground"
                  : "bg-success-foreground")
              }
            />
            {t("dsh.modelAuditView.modes." + snapshot.mode)}
          </span>
        )}
        {!snapshot && !failed && <span role="status">{t("dsh.loading")}</span>}
        {canConfigure && (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="text-sm [@media(pointer:coarse)]:min-h-11"
            aria-expanded={open}
            aria-controls={panelId}
            onClick={() => setOpen((old) => !old)}
          >
            {t("dsh.modelAuditView.configure")}
          </Button>
        )}
        <Button
          type="button"
          size="sm"
          variant="ghost"
          className="text-sm [@media(pointer:coarse)]:min-h-11"
          disabled={busy}
          onClick={() => setRevision((old) => old + 1)}
        >
          {t("dsh.modelAuditView.refresh_mode")}
        </Button>
      </div>
      <p
        id={`${panelId}-collection-hint`}
        className="col-span-full text-xs text-muted-foreground"
      >
        {t("dsh.modelAuditView.collectionHint")}
      </p>
      {snapshot && !canCaptureContent && (
        <p
          role="alert"
          className="col-span-full rounded-md border border-input bg-muted/50 px-3 py-2 text-sm"
        >
          {t(
            snapshot.content_available === undefined
              ? "dsh.modelAuditView.contentReadinessUnknown"
              : snapshot.mode === "CONTENT"
                ? "dsh.modelAuditView.contentKeyLost"
                : "dsh.modelAuditView.contentKeyMissing",
          )}
        </p>
      )}
      {(failed || saveFailed) && (
        <p role="alert" className="col-span-full text-sm text-destructive">
          {t("dsh.modelAuditView.loadError")}
        </p>
      )}
      {canConfigure && open && (
        <section
          id={panelId}
          className="col-span-full space-y-3 rounded-lg bg-muted/50 p-4"
        >
          <h3 className="text-sm font-medium">
            {t("dsh.modelAuditView.mode")}
          </h3>
          <p className="text-xs text-muted-foreground">
            {t("dsh.modelAuditView.modeHint")}
          </p>
          <div className="flex flex-wrap items-center gap-2 [&_button]:[@media(pointer:coarse)]:min-h-11">
            <DshChoice
              label={t("dsh.modelAuditView.mode")}
              value={selected}
              options={(["OFF", "METADATA", "CONTENT"] as const).map(
                (value) => ({
                  value,
                  label: t("dsh.modelAuditView.modes." + value),
                  disabled: value === "CONTENT" && !canCaptureContent,
                }),
              )}
              disabled={!snapshot || busy}
              onChange={(value) => setSelected(value as AuditMode)}
            />
            <Button
              type="button"
              size="sm"
              className="text-sm"
              disabled={
                !tenantId ||
                !snapshot ||
                busy ||
                selected === snapshot.mode ||
                (selected === "CONTENT" && !canCaptureContent)
              }
              onClick={handleSave}
            >
              {t("dsh.save")}
            </Button>
            {snapshot && canCaptureContent && (
              <span className="text-xs text-muted-foreground">
                {t("dsh.modelAuditView.contentKeyReady")}
              </span>
            )}
          </div>
        </section>
      )}
    </>
  );
}
