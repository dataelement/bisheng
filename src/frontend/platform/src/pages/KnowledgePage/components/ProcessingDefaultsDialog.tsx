import { Button } from "@bisheng/ui";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/bs-ui/dialog";
import {
  knowledgeSpaceApi,
  type KnowledgeSpaceApi,
  type ProcessingSettingsRead,
} from "@/controllers/API/knowledgeSpace";
import {
  knowledgeQueryKeys,
  useKnowledgeProcessingSettings,
  type KnowledgeQueryScope,
} from "@/controllers/hooks/knowledge";
import { showApiError } from "@/controllers/request";
import {
  ProcessingDefaultsEditor,
  processingDefaultsToDraft,
  validateProcessingDefaultsDraft,
  type ProcessingDefaultsDraft,
} from "./ProcessingDefaultsEditor";

interface ProcessingDefaultsDialogProps {
  scope: KnowledgeQueryScope;
  spaceId: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved?: (settings: ProcessingSettingsRead) => void;
  api?: KnowledgeSpaceApi;
}
type ContentProps = Omit<ProcessingDefaultsDialogProps, "open">;

export function ProcessingDefaultsDialog(props: ProcessingDefaultsDialogProps) {
  return (
    <Dialog open={props.open} onOpenChange={props.onOpenChange}>
      {props.open && <ProcessingDefaultsContent {...props} />}
    </Dialog>
  );
}
function ProcessingDefaultsContent({
  scope,
  spaceId,
  onOpenChange,
  onSaved,
  api = knowledgeSpaceApi,
}: ContentProps) {
  const { t } = useTranslation("knowledge");
  const client = useQueryClient();
  const query = useKnowledgeProcessingSettings(scope, spaceId, api);
  const key = JSON.stringify(knowledgeQueryKeys.settings(scope, spaceId));
  const epoch = useMemo(() => ({ key, api }), [key, api]);
  const current = useRef<typeof epoch | null>(epoch);
  current.current = epoch;
  const [loaded, setLoaded] = useState<{
    epoch: typeof epoch;
    version: number;
    draft: ProcessingDefaultsDraft;
  } | null>(null);
  const [saving, setSaving] = useState<typeof epoch | null>(null);
  const refetch = query.refetch;
  // Manual refresh must preserve the existing query hook's enabled boundary.
  const canLoad =
    Boolean(scope.identityKey) &&
    Number.isSafeInteger(scope.tenantId) &&
    scope.tenantId > 0 &&
    Number.isSafeInteger(spaceId) &&
    spaceId > 0;
  const handleLoad = async () => {
    if (!canLoad || current.current !== epoch) return;
    try {
      const result = await refetch({ cancelRefetch: false });
      if (current.current === epoch && result.isSuccess && result.data) {
        setLoaded({
          epoch,
          version: result.data.config_version,
          draft: processingDefaultsToDraft(result.data.effective_defaults),
        });
      }
    } catch (error) {
      if (current.current === epoch) showApiError(error);
    }
  };
  useEffect(() => {
    current.current = epoch;
    setLoaded(null);
    if (canLoad)
      void refetch({ cancelRefetch: false })
        .then((result) => {
          if (current.current === epoch && result.isSuccess && result.data) {
            setLoaded({
              epoch,
              version: result.data.config_version,
              draft: processingDefaultsToDraft(result.data.effective_defaults),
            });
          }
        })
        .catch((error) => {
          if (current.current === epoch) showApiError(error);
        });
    return () => {
      if (current.current === epoch) current.current = null;
    };
  }, [epoch, refetch, canLoad]);
  const active = loaded?.epoch === epoch ? loaded : null;
  const pending = saving === epoch;
  const validation = active
    ? validateProcessingDefaultsDraft(active.draft)
    : null;
  const handleSave = async () => {
    if (!active || pending || !validation?.ok || current.current !== epoch)
      return;
    setSaving(epoch);
    try {
      const result = await api.updateProcessingSettings(spaceId, {
        expected_config_version: active.version,
        defaults: validation.value,
      });
      if (current.current !== epoch) return;
      await client.invalidateQueries({
        queryKey: knowledgeQueryKeys.settings(scope, spaceId),
      });
      if (current.current !== epoch) return;
      onSaved?.(result);
      if (current.current === epoch) onOpenChange(false);
    } catch (error) {
      if (current.current === epoch) showApiError(error);
    } finally {
      if (current.current === epoch) setSaving(null);
    }
  };
  return (
    <DialogContent
      close={!pending}
      className="sm:max-w-3xl max-h-[90vh] overflow-y-auto"
      onEscapeKeyDown={(event) => {
        if (pending) event.preventDefault();
      }}
      onPointerDownOutside={(event) => {
        if (pending) event.preventDefault();
      }}
    >
      <DialogHeader>
        <DialogTitle>{t("f118.defaults_title")}</DialogTitle>
      </DialogHeader>
      <p className="text-sm text-text-2">{t("f118.future_uploads_only")}</p>
      {active ? (
        <ProcessingDefaultsEditor
          value={active.draft}
          disabled={pending}
          onChange={(draft) => setLoaded({ ...active, draft })}
        />
      ) : query.isError ? (
        <div role="alert">
          <p>{t("f118.load_failed")}</p>
          <Button
            onClick={() => {
              void handleLoad();
            }}
          >
            {t("retry")}
          </Button>
        </div>
      ) : (
        <p role="status">{t("f118.loading_defaults")}</p>
      )}
      <DialogFooter>
        <Button
          variant="outlined"
          color="default"
          disabled={pending}
          onClick={() => onOpenChange(false)}
        >
          {t("cancel")}
        </Button>
        <Button
          disabled={pending || !validation?.ok}
          onClick={() => {
            void handleSave();
          }}
        >
          {t("save")}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}
