import { Button, Input, toast } from "@bisheng/ui";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { readMetadataSchema } from "@/controllers/API/knowledgeProcessing";
import { updateFileMetadata, type FileMetadata } from "@/controllers/API/knowledgeIndex";
import { knowledgeQueryKeys, type KnowledgeQueryScope } from "@/controllers/hooks/knowledge";
import { showApiError } from "@/controllers/request";
interface SpaceFileMetadataDialogProps {
  scope: KnowledgeQueryScope;
  spaceId: number;
  fileId: number;
  info: FileMetadata;
  onClose: () => void;
  onSaved: () => Promise<unknown>;
}
export function SpaceFileMetadataDialog({
  scope,
  spaceId,
  fileId,
  info,
  onClose,
  onSaved,
}: SpaceFileMetadataDialogProps) {
  const { t } = useTranslation("knowledge");
  const [values, setValues] = useState(() =>
    Object.fromEntries(
      Object.entries(info.user_metadata ?? {}).map(([key, row]) => [key, String(row.field_value ?? "")]),
    ),
  );
  const [busy, setBusy] = useState(false);
  const alive = useRef(true);
  const schema = useQuery({
    queryKey: [...knowledgeQueryKeys.space(scope, spaceId), "metadata-schema"],
    queryFn: () => readMetadataSchema(spaceId),
    cacheTime: 0,
    retry: false,
  });
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  useEffect(() => {
    if (schema.error) showApiError(schema.error);
  }, [schema.error]);
  const handleSave = async () => {
    if (busy || !alive.current) return;
    setBusy(true);
    try {
      await updateFileMetadata(fileId, values);
      if (!alive.current) return;
      await onSaved();
      if (!alive.current) return;
      toast.show({ type: "success", message: t("detail.saved") });
      onClose();
    } catch (error) {
      if (alive.current) showApiError(error);
    } finally {
      if (alive.current) setBusy(false);
    }
  };
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !busy) onClose();
      }}
    >
      <DialogContent
        aria-describedby={undefined}
        close={!busy}
        onEscapeKeyDown={(event) => {
          if (busy) event.preventDefault();
        }}
        onPointerDownOutside={(event) => {
          if (busy) event.preventDefault();
        }}
      >
        <DialogHeader>
          <DialogTitle>{t("metadialog.title")}</DialogTitle>
        </DialogHeader>
        <fieldset disabled={busy} className="space-y-3">
          {Object.entries(values).map(([key, value]) => (
            <div key={key} className="flex items-end gap-2">
              <label className="flex-1 space-y-1">
                {key}
                <Input
                  value={value}
                  onChange={(event) => setValues({ ...values, [key]: event.target.value })}
                />
              </label>
              <Button
                variant="text"
                onClick={() =>
                  setValues(Object.fromEntries(Object.entries(values).filter(([name]) => name !== key)))
                }
              >
                {t("delete")}
              </Button>
            </div>
          ))}
          <div className="flex flex-wrap gap-2">
            {schema.data?.fields
              .filter((field) => field.field_name.trim() && !(field.field_name in values))
              .map((field) => (
                <Button
                  key={field.field_name}
                  variant="outlined"
                  onClick={() => setValues({ ...values, [field.field_name]: "" })}
                >
                  {field.field_name}
                </Button>
              ))}
          </div>
          {!Object.keys(values).length && <p>{t("detail.no_metadata")}</p>}
          {schema.isError && (
            <Button
              variant="text"
              onClick={() => {
                void schema.refetch();
              }}
            >
              {t("retry")}
            </Button>
          )}
        </fieldset>
        <DialogFooter>
          <Button variant="outlined" disabled={busy} onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button
            disabled={busy}
            onClick={() => {
              void handleSave();
            }}
          >
            {t("save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
