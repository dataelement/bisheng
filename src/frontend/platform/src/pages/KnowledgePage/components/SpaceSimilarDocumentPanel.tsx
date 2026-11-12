import { Button } from "@bisheng/ui";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { knowledgeVersionsApi } from "@/controllers/API/knowledgeVersions";
import { showApiError } from "@/controllers/request";
import {
  SpaceVersionRelationPanel,
  type SpaceVersionRelationPanelProps,
} from "./SpaceVersionRelationPanel";

export function SpaceSimilarDocumentPanel(
  props: Omit<SpaceVersionRelationPanelProps, "mode">,
) {
  const { t } = useTranslation("knowledge");
  const [busy, setBusy] = useState(false),
    [uncertain, setUncertain] = useState(false);
  const writing = useRef(false),
    lifetime = useRef<AbortController>();
  const { onBusyChange } = props;
  const handleBusy = useCallback(
    (value: boolean) => {
      setBusy(value);
      onBusyChange?.(value);
    },
    [onBusyChange],
  );
  useEffect(() => {
    const controller = new AbortController();
    lifetime.current = controller;
    return () => {
      controller.abort();
      onBusyChange?.(false);
    };
  }, [onBusyChange]);
  const handleKeep = () => {
    const controller = lifetime.current;
    if (
      !controller ||
      controller.signal.aborted ||
      writing.current ||
      busy ||
      uncertain
    )
      return;
    let attempted = false;
    bsConfirm({
      title: t("versions.keep_two"),
      desc: t("versions.keep_two_hint"),
      signal: controller.signal,
      onOk: async (close) => {
        if (controller.signal.aborted || writing.current || attempted) return;
        attempted = true;
        writing.current = true;
        setBusy(true);
        onBusyChange?.(true);
        try {
          await (props.api ?? knowledgeVersionsApi).dismissSpaceSimilarFile(
            props.fileId,
            controller.signal,
          );
          if (controller.signal.aborted) return;
          close();
          await props.onChanged();
        } catch (error) {
          if (!controller.signal.aborted) {
            setUncertain(true);
            close();
            showApiError(error);
          }
        } finally {
          writing.current = false;
          if (!controller.signal.aborted) {
            setBusy(false);
            onBusyChange?.(false);
          }
        }
      },
    });
  };
  return (
    <div className="space-y-3">
      <SpaceVersionRelationPanel
        {...props}
        mode="link"
        disabled={busy || uncertain}
        onBusyChange={handleBusy}
      />
      <section className="space-y-2 rounded-md border p-3">
        <p className="text-sm text-muted-foreground">
          {t("versions.keep_two_hint")}
        </p>
        {uncertain && <p role="alert">{t("versions.uncertain")}</p>}
        <Button
          variant="outlined"
          disabled={busy || uncertain}
          onClick={handleKeep}
        >
          {t("versions.keep_two")}
        </Button>
      </section>
    </div>
  );
}
