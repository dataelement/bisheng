import { Button } from '@bisheng/ui';

import request from "@/controllers/request";
import { Switch } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

interface ModelVisionSwitchProps {
  modelId: number;
}

export function ModelVisionSwitch({ modelId }: ModelVisionSwitchProps) {
  const { t } = useTranslation("model");
  const [vision, setVision] = useState(false);
  const [pending, setPending] = useState(true);
  const [error, setError] = useState(false);
  const [revision, setRevision] = useState(0);
  const [loaded, setLoaded] = useState(false);
  const url = `/api/v1/dsh/admin/models/${modelId}/vision`;
  useEffect(() => {
    let current = true;
    setPending(true);
    setLoaded(false);
    request
      .get<unknown, { vision: boolean }>(url, { timeout: 15000 })
      .then((data) => {
        if (typeof data?.vision !== "boolean") throw new Error("Invalid capability response");
        if (current) {
          setVision(data.vision);
          setLoaded(true);
          setError(false);
        }
      })
      .catch(() => {
        if (current) setError(true);
      })
      .finally(() => {
        if (current) setPending(false);
      });
    return () => {
      current = false;
    };
  }, [url, revision]);
  const save = async (value: boolean) => {
    setPending(true);
    setError(false);
    try {
      const data: { vision: boolean } = await request.put(url, { vision: value }, { timeout: 15000 });
      if (typeof data?.vision !== "boolean") throw new Error("Invalid capability response");
      setVision(data.vision);
    } catch {
      setError(true);
    } finally {
      setPending(false);
    }
  };
  return (
    <div className="flex items-center gap-2">
      <Switch
        checked={vision}
        disabled={pending || !loaded}
        aria-label={t("model.supportsImages")}
        onCheckedChange={save}
      />
      {pending && <Outlined.Loading className="size-4 animate-spin" aria-label={t("model.loading")} />}
      {error && (
        <Button type="button" variant="link" color="danger" size="small" onClick={() => setRevision((value) => value + 1)}>
          <Outlined.Refresh className="size-3" />
          {t("model.visionRetry")}
        </Button>
      )}
    </div>
  );
}
