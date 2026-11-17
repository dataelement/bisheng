import { Button, toast } from "@bisheng/ui";
import { useTranslation } from "react-i18next";
import { Dialog } from "@/components/bs-ui/dialog";
import { SpacePanelFrame } from "./SpacePanelFrame";
import type {
  KnowledgeSpaceApi,
  ProcessingSettingsRead,
} from "@/controllers/API/knowledgeSpace";
import type { KnowledgeQueryScope } from "@/controllers/hooks/knowledge";
import { showApiError } from "@/controllers/request";
import { ProcessingDefaultsEditor } from "./ProcessingDefaultsEditor";
import { useProcessingDefaultsDraft } from "./useProcessingDefaultsDraft";

interface ProcessingDefaultsDialogProps {
  scope: KnowledgeQueryScope;
  spaceId: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved?: (settings: ProcessingSettingsRead) => void;
  api?: KnowledgeSpaceApi;
}
interface ProcessingDefaultsPanelProps extends Omit<
  ProcessingDefaultsDialogProps,
  "open" | "onOpenChange"
> {
  presentation?: "page" | "inline";
}
interface ContentProps extends ProcessingDefaultsPanelProps {
  onOpenChange?: ProcessingDefaultsDialogProps["onOpenChange"];
}

export function ProcessingDefaultsPanel({
  presentation = "page",
  ...props
}: ProcessingDefaultsPanelProps) {
  return <ProcessingDefaultsContent {...props} presentation={presentation} />;
}

export function ProcessingDefaultsDialog(props: ProcessingDefaultsDialogProps) {
  return (
    <Dialog open={props.open} onOpenChange={props.onOpenChange}>
      {props.open && <ProcessingDefaultsContent {...props} />}
    </Dialog>
  );
}

interface ProcessingDefaultsFieldsProps {
  form: Pick<
    ReturnType<typeof useProcessingDefaultsDraft>,
    "draft" | "error" | "pending" | "load" | "setDraft"
  >;
  compact?: boolean;
  disabled?: boolean;
}

export function ProcessingDefaultsFields({
  form,
  compact = false,
  disabled = false,
}: ProcessingDefaultsFieldsProps) {
  const { t } = useTranslation("knowledge");
  return (
    <>
      <p className={compact ? "text-body text-text-3" : "text-sm text-text-2"}>
        {t("f118.future_uploads_only")}
      </p>
      {form.draft ? (
        <ProcessingDefaultsEditor
          value={form.draft}
          disabled={disabled || form.pending}
          onChange={form.setDraft}
          compact={compact}
        />
      ) : form.error ? (
        <div role="alert">
          <p>{t("f118.load_failed")}</p>
          <Button disabled={disabled} onClick={() => void form.load()}>
            {t("retry")}
          </Button>
        </div>
      ) : (
        <p role="status">{t("f118.loading_defaults")}</p>
      )}
    </>
  );
}

function ProcessingDefaultsContent({
  scope,
  spaceId,
  onOpenChange,
  onSaved,
  api,
  presentation,
}: ContentProps) {
  const { t } = useTranslation("knowledge");
  const form = useProcessingDefaultsDraft(scope, spaceId, api);
  const handleSave = async () => {
    if (form.pending || !form.valid) return;
    try {
      const result = await form.save();
      if (!result || !form.isCurrent()) return;
      onSaved?.(result);
      if (!form.isCurrent()) return;
      if (presentation) toast.show({ type: "success", message: t("detail.saved") });
      else onOpenChange?.(false);
    } catch (error) {
      if (form.isCurrent()) showApiError(error);
    }
  };
  return (
    <SpacePanelFrame
      title={t("f118.defaults_title")}
      presentation={presentation}
      busy={form.pending}
      footer={
        <>
          {!presentation && (
            <Button
              variant="outlined"
              color="default"
              disabled={form.pending}
              onClick={() => onOpenChange?.(false)}
            >
              {t("cancel")}
            </Button>
          )}
          <Button
            disabled={form.pending || !form.valid}
            onClick={() => {
              void handleSave();
            }}
          >
            {t("save")}
          </Button>
        </>
      }
    >
      <ProcessingDefaultsFields form={form} compact={presentation === "inline"} />
    </SpacePanelFrame>
  );
}
