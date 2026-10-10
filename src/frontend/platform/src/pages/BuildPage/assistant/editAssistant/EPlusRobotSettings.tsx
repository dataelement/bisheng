import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Badge } from "@/components/bs-ui/badge";
import { Button } from "@/components/bs-ui/button";
import { Input, PasswordInput } from "@/components/bs-ui/input";
import MultiSelect from "@/components/bs-ui/select/multi";
import { toast } from "@/components/bs-ui/toast/use-toast";
import {
  deleteEPlusBotConfigApi,
  getEPlusBotConfigApi,
  listEPlusBindableSpacesApi,
  saveEPlusBotConfigApi,
} from "@/controllers/API/eplus";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { getRobotDebugStatus } from "@/controllers/API/eplusDebug";
import type {
  EPlusBindableSpace,
  EPlusBotConfig,
  EPlusBotConfigInput,
  EPlusConnectionStatus,
} from "@/types/eplus";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

interface EPlusRobotSettingsProps {
  assistantId: string;
}

interface RobotFormState {
  botId: string;
  connectionUrl: string;
  secret: string;
  spaceIds: string[];
}

const emptyForm: RobotFormState = {
  botId: "",
  connectionUrl: "",
  secret: "",
  spaceIds: [],
};

function formFromConfig(config: EPlusBotConfig | null): RobotFormState {
  if (!config) return emptyForm;
  return {
    botId: config.bot_id,
    connectionUrl: config.connection_url,
    secret: "",
    spaceIds: config.space_ids.map(String),
  };
}

function connectionStatusKey(status?: EPlusConnectionStatus): string {
  if (!status) return "build.eplusNotConfigured";
  const keys: Record<EPlusConnectionStatus, string> = {
    DISABLED: "build.eplusStatusDisabled",
    CONNECTING: "build.eplusStatusConnecting",
    AUTHENTICATED: "build.eplusStatusAuthenticated",
    RETRYING: "build.eplusStatusRetrying",
    TAKEN_OVER: "build.eplusStatusTakenOver",
    ERROR: "build.eplusStatusError",
  };
  return keys[status];
}

function statusVariant(status?: EPlusConnectionStatus) {
  if (status === "AUTHENTICATED") return "default" as const;
  if (status === "ERROR" || status === "TAKEN_OVER") return "destructive" as const;
  if (status === "DISABLED" || !status) return "outline" as const;
  return "secondary" as const;
}

export function EPlusRobotSettings({ assistantId }: EPlusRobotSettingsProps) {
  const { t } = useTranslation();
  const [config, setConfig] = useState<EPlusBotConfig | null>(null);
  const [spaces, setSpaces] = useState<EPlusBindableSpace[]>([]);
  const [form, setForm] = useState<RobotFormState>(emptyForm);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState("");
  const [debugAvailable, setDebugAvailable] = useState(false);

  useEffect(() => {
    let active = true;
    void getRobotDebugStatus().then(available => { if (active) setDebugAvailable(available); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    let active = true;
    setLoading(true);
    void captureAndAlertRequestErrorHoc(
      Promise.all([
        getEPlusBotConfigApi(assistantId),
        listEPlusBindableSpacesApi(assistantId),
      ]),
    ).then((result) => {
      if (!active) return;
      setLoading(false);
      if (!Array.isArray(result)) return;
      const [nextConfig, nextSpaces] = result as [
        EPlusBotConfig | null,
        EPlusBindableSpace[],
      ];
      setConfig(nextConfig);
      setForm(formFromConfig(nextConfig));
      setSpaces(nextSpaces);
    });
    return () => {
      active = false;
    };
  }, [assistantId]);

  const spaceOptions = useMemo(
    () => spaces.map((space) => ({ label: space.name, value: String(space.id) })),
    [spaces],
  );

  const updateForm = <K extends keyof RobotFormState>(key: K, value: RobotFormState[K]) => {
    setForm((current) => ({ ...current, [key]: value }));
    setFormError("");
  };

  const validate = () => {
    const secretReady = config?.secret_configured || Boolean(form.secret.trim());
    if (!form.botId.trim() || !form.connectionUrl.trim() || !secretReady) {
      setFormError("build.eplusRequiredWhenEnabled");
      return false;
    }
    if (!/^wss?:\/\//i.test(form.connectionUrl.trim())) {
      setFormError("build.eplusInvalidWebSocketUrl");
      return false;
    }
    return true;
  };

  const handleSave = async () => {
    if (!validate()) return;
    const payload: EPlusBotConfigInput = {
      bot_id: form.botId.trim(),
      connection_url: form.connectionUrl.trim(),
      secret: form.secret.trim() || undefined,
      remove_ca: false,
      media_hosts: [],
      space_ids: form.spaceIds.map(Number),
      enabled: true,
    };
    setSaving(true);
    const saved = await captureAndAlertRequestErrorHoc(
      saveEPlusBotConfigApi(assistantId, payload),
    );
    setSaving(false);
    if (!saved || typeof saved !== "object") return;
    const nextConfig = saved as EPlusBotConfig;
    setConfig(nextConfig);
    setForm(formFromConfig(nextConfig));
    toast({
      title: t("prompt"),
      description: t("build.eplusSaved"),
      variant: "success",
    });
  };

  const handleDisconnect = () => {
    bsConfirm({
      desc: t("build.eplusDisconnectConfirm"),
      onOk: async (close) => {
        const disabled = await captureAndAlertRequestErrorHoc(
          deleteEPlusBotConfigApi(assistantId),
        );
        if (disabled !== true) return;
        setConfig(null);
        setForm(emptyForm);
        close();
        toast({
          title: t("prompt"),
          description: t("build.eplusDisconnected"),
          variant: "success",
        });
      },
    });
  };

  if (loading) {
    return <p className="px-6 py-4 text-sm text-muted-foreground">{t("loading")}</p>;
  }

  return (
    <div className="space-y-4 px-6 py-2">
      <div className="flex items-center justify-between gap-4">
        <div>
          <p className="text-sm font-medium">{t("build.eplusRobot")}</p>
          <p className="mt-1 text-xs text-muted-foreground">{t("build.eplusScopeNotice")}</p>
        </div>
        <Badge className="shrink-0 whitespace-nowrap" variant={statusVariant(config?.connection_status)}>
          {t(connectionStatusKey(config?.connection_status))}
        </Badge>
      </div>

      <div>
        <label htmlFor="eplus-bot-id" className="bisheng-label">
          {t("build.eplusBotId")}
        </label>
        <Input
          id="eplus-bot-id"
          className="mt-2"
          value={form.botId}
          onChange={(event) => updateForm("botId", event.target.value)}
        />
      </div>

      <div>
        <label htmlFor="eplus-connection-url" className="bisheng-label">
          {t("build.eplusConnectionUrl")}
        </label>
        <Input
          id="eplus-connection-url"
          className="mt-2"
          value={form.connectionUrl}
          placeholder="wss://eplus.example.com/im_openws?bizid=1"
          onChange={(event) => updateForm("connectionUrl", event.target.value)}
        />
        {form.connectionUrl.trim().toLowerCase().startsWith("ws://") && (
          <p className="mt-1 text-xs text-destructive">{t("build.eplusWsWarning")}</p>
        )}
      </div>

      <div>
        <label htmlFor="eplus-secret" className="bisheng-label">
          {t("build.eplusSecret")}
        </label>
        <PasswordInput
          id="eplus-secret"
          className="mt-2"
          value={form.secret}
          placeholder={
            config?.secret_configured
              ? t("build.eplusSecretConfigured")
              : t("build.eplusSecretRequired")
          }
          onChange={(event) => updateForm("secret", event.target.value)}
        />
      </div>

      <div>
        <label className="bisheng-label">{t("build.eplusKnowledgeSpaces")}</label>
        <MultiSelect
          multiple
          className="mt-2"
          options={spaceOptions}
          value={form.spaceIds}
          placeholder={t("build.eplusKnowledgeSpacesPlaceholder")}
          searchPlaceholder={t("build.searchBaseName")}
          onChange={(values) => updateForm("spaceIds", values)}
        />
      </div>

      {formError && <p className="text-xs text-destructive">{t(formError)}</p>}

      <div className="flex justify-end gap-2">
        {debugAvailable && config && (
          <Button variant="link" onClick={() => window.open(`${__APP_ENV__.BASE_URL}/robot-debug?assistantId=${encodeURIComponent(assistantId)}`, "_blank", "noopener,noreferrer")}>
            {t("build.robotDebug.open")}
          </Button>
        )}
        {config && (
          <Button variant="outline" disabled={saving} onClick={handleDisconnect}>
            {t("build.eplusDisconnect")}
          </Button>
        )}
        <Button disabled={saving} onClick={() => void handleSave()}>
          {t("build.eplusSave")}
        </Button>
      </div>
    </div>
  );
}
