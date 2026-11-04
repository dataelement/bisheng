import { Button, Input, toast } from '@bisheng/ui';


import { saveDshManagementSettings, type DshManagementSettings } from "@/controllers/API/dshSettings";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

interface SettingsPanelProps {
  settings: DshManagementSettings;
  canEdit: boolean;
}

export function SettingsPanel({ settings, canEdit }: SettingsPanelProps) {
  const { t } = useTranslation();
  const [download, setDownload] = useState(settings.download_url ?? "");
  const [launch, setLaunch] = useState(settings.launch_url);
  const [saving, setSaving] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [status, setStatus] = useState<"error" | null>(null);
  const lock = useRef(false);
  const dirty = useRef(false);
  useEffect(() => {
    if (!dirty.current) {
      setDownload(settings.download_url ?? "");
      setLaunch(settings.launch_url);
    }
  }, [settings.enabled, settings.download_url, settings.launch_url]);
  async function handleSave() {
    if (lock.current || !canEdit || !isEditing) return;
    lock.current = true;
    setSaving(true);
    setStatus(null);
    try {
      const result = await saveDshManagementSettings({
        enabled: true,
        download_url: download.trim() || null,
        launch_url: launch.trim(),
      });
      setDownload(result.download_url ?? "");
      setLaunch(result.launch_url);
      dirty.current = false;
      setIsEditing(false);
      toast.show({ type: "success", message: t("dsh.settingsSaved") });
    } catch {
      setStatus("error");
    } finally {
      lock.current = false;
      setSaving(false);
    }
  }
  return (
    <section className="shrink-0 space-y-3 rounded-lg">
      <div className="grid gap-3 md:grid-cols-2">
        <label className="min-w-0 space-y-1">
          <span className="text-body font-normal text-text-1">{t("dsh.launchAddress")}</span>
          <Input value={launch} disabled={!canEdit || !isEditing || saving} onChange={(event) => {
              dirty.current = true;
              setLaunch(event.target.value);
              setStatus(null);
            }} />
          <p className="text-caption font-normal text-text-3">{t("dsh.launchAddressHelp")}</p>
        </label>
        <label className="min-w-0 space-y-1">
          <span className="text-body font-normal text-text-1">{t("dsh.downloadAddress")}</span>
          <Input value={download} disabled={!canEdit || !isEditing || saving} onChange={(event) => {
              dirty.current = true;
              setDownload(event.target.value);
              setStatus(null);
            }} />
          <p className="text-caption font-normal text-text-3">{t("dsh.downloadAddressHelp")}</p>
        </label>
      </div>
      <div className="flex justify-start">
        {canEdit ? (
          <Button disabled={saving} onClick={() => {
            if (isEditing) return handleSave();
            setStatus(null);
            setIsEditing(true);
          }}>
            {t(isEditing ? "dsh.saveSettings" : "dsh.editSettings")}
          </Button>
        ) : (
          <p>{t("dsh.settingsAdminOnly")}</p>
        )}
      </div>
      {status === "error" && (
        <p role="alert">{t("dsh.settingsSaveFailed")}</p>
      )}
    </section>
  );
}
