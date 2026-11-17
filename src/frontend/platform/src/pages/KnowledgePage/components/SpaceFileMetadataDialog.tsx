import { Button, Input, Select, toast } from "@bisheng/ui";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";
import { updateFileMetadata, type FileMetadata } from "@/controllers/API/knowledgeIndex";
import type { KnowledgeQueryScope } from "@/controllers/hooks/knowledge";
import { showApiError } from "@/controllers/request";
import { useSpaceMetadataSchema } from "../hooks/useSpaceMetadataSchema";
import { FileMetadataValueFields } from "./FileMetadataValueFields";
import { SpaceProcessingProgress } from "./SpaceProcessingProgress";

interface SpaceFileMetadataDialogProps {
  scope: KnowledgeQueryScope;
  spaceId: number;
  fileId: number;
  info: FileMetadata;
  onClose: () => void;
  onSaved: () => Promise<unknown>;
}
export function SpaceFileMetadataDialog(props: SpaceFileMetadataDialogProps) {
  return <FileMetadataEditor key={JSON.stringify([props.scope, props.spaceId, props.fileId])} {...props} />;
}
function FileMetadataEditor({ scope, spaceId, fileId, info, onClose, onSaved }: SpaceFileMetadataDialogProps) {
  const { t } = useTranslation("knowledge");
  const selectLabels = useSelectLabels();
  const [values, setValues] = useState<Record<string, string>>(() => Object.fromEntries(
    Object.entries(info.user_metadata ?? {}).map(([key, row]) => [key, String(row.field_value ?? "")]),
  ));
  const [view, setView] = useState<"values" | "add" | "create">("values");
  const [name, setName] = useState("");
  const [fieldType, setFieldType] = useState("string");
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [schemaEditing, setSchemaEditing] = useState(false);
  const [awaitingField, setAwaitingField] = useState<string | null>(null);
  const alive = useRef(true), locked = useRef(false);
  const metadata = useSpaceMetadataSchema({ scope, spaceId, enabled: schemaEditing });
  const uncertain = metadata.uncertain;
  const fields = metadata.schema.data?.fields;
  const types = useMemo(() => ({
    ...Object.fromEntries(Object.entries(info.user_metadata ?? {}).map(([key, row]) => [key, row.field_type ?? "string"])),
    ...Object.fromEntries((fields ?? []).map(field => [field.field_name, field.field_type])),
  }), [fields, info.user_metadata]);
  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);
  useEffect(() => {
    if (awaitingField && metadata.jobState === "succeeded" && fields?.some(field => field.field_name === awaitingField)) {
      setValues(previous => ({ ...previous, [awaitingField]: "" }));
      setAwaitingField(null);
      setName("");
      setError("");
      setView("values");
    }
  }, [awaitingField, metadata.jobState, fields]);
  const handleSave = async () => {
    if (locked.current || !alive.current || awaitingField || !metadata.schema.isSuccess) return;
    if (Object.entries(values).some(([key, value]) => (types[key] === "number" || types[key] === "time") && value.trim() && (!Number.isFinite(Number(value)) || (types[key] === "time" && !Number.isFinite(new Date(Number(value) * 1000).getTime()))))) {
      setError(t("inputInvalid"));
      return;
    }
    locked.current = true;
    setBusy(true);
    setError("");
    try {
      await updateFileMetadata(fileId, values);
      if (!alive.current) return;
      await onSaved();
      if (!alive.current) return;
      toast.show({ type: "success", message: t("detail.saved") });
      onClose();
    } catch (cause) {
      if (alive.current) showApiError(cause);
    } finally {
      locked.current = false;
      if (alive.current) setBusy(false);
    }
  };
  const handleCreate = async () => {
    if (locked.current || !alive.current || !metadata.canEdit || awaitingField) return;
    const trimmed = name.trim();
    const validation = !trimmed ? "nameRequired" : trimmed.length > 255 ? "nameTooLong"
      : !/^[a-z][a-z0-9_]*$/.test(trimmed) ? "nameFormatError"
      : fields?.some(field => field.field_name === trimmed) ? "nameExists" : null;
    if (validation) { setError(t(validation)); return; }
    locked.current = true;
    setBusy(true);
    setError("");
    try {
      await metadata.mutations.add(trimmed, fieldType);
      if (alive.current) setAwaitingField(trimmed);
    } catch {
      // The shared mutation owner presents the original error and retains its idempotency key.
    } finally {
      locked.current = false;
      if (alive.current) setBusy(false);
    }
  };
  const available = fields?.filter(field => field.field_name.trim() && !(field.field_name in values) && field.field_name.includes(search)) ?? [];
  const creating = busy || Boolean(awaitingField);
  return <Dialog open onOpenChange={open => { if (!open && !busy) onClose(); }}>
    <DialogContent aria-describedby={undefined} close={!busy}
      onEscapeKeyDown={event => { if (busy) event.preventDefault(); }}
      onPointerDownOutside={event => { if (busy) event.preventDefault(); }}>
      <DialogHeader><DialogTitle>{t("metadialog.title")}</DialogTitle></DialogHeader>
      <fieldset disabled={busy} className="max-h-[60vh] space-y-3 overflow-y-auto">
        {view === "values" ? <>
          <Button variant="outlined" disabled={!metadata.schema.isSuccess || Boolean(awaitingField)} onClick={() => { setView("add"); setError(""); }}>{t("metadatainfor.addMetadata")}</Button>
          <FileMetadataValueFields values={values} types={types}
            onChange={(key, value) => setValues(previous => ({ ...previous, [key]: value }))}
            onRemove={key => setValues(previous => Object.fromEntries(Object.entries(previous).filter(([name]) => name !== key)))} />
          {!Object.keys(values).length && <p>{t("detail.no_metadata")}</p>}
        </> : view === "add" ? <>
          <Input aria-label={t("fileMetadata.searchFields")} placeholder={t("fileMetadata.searchFields")} value={search} onChange={event => setSearch(event.target.value)} />
          <div className="flex flex-wrap gap-2">
            {available.map(field => <Button key={field.field_name} variant="outlined" onClick={() => {
              setValues(previous => ({ ...previous, [field.field_name]: "" })); setView("values");
            }}>{field.field_name}</Button>)}
            {!available.length && <p>{t("fileMetadata.noAvailableFields")}</p>}
          </div>
          <Button onClick={() => { setSchemaEditing(true); setView("create"); }}>{t("metadatainfor.createMetadata")}</Button>
        </> : <>
          <p>{t("fileMetadata.schemaScopeHint")}</p>
          <label className="block space-y-1">{t("name")}<Input aria-label={t("name")} maxLength={255} value={name} disabled={creating || uncertain} onChange={event => { setName(event.target.value); setError(""); }} /></label>
          <Select {...selectLabels} aria-label={t("fileMetadata.fieldType")} value={fieldType} disabled={creating || uncertain}
            options={[{ value: "string", label: t("fileMetadata.typeString") }, { value: "number", label: t("fileMetadata.typeNumber") }, { value: "time", label: t("fileMetadata.typeTime") }]}
            onChange={value => { if (typeof value === "string") setFieldType(value); }} />
          {uncertain && <p role="alert">{t("fileMetadata.uncertain")}</p>}
          {awaitingField && <p role="status">{t("fileMetadata.schemaPending")}</p>}
          {!awaitingField && <Button disabled={busy || !metadata.canEdit} onClick={() => { void handleCreate(); }}>{t("fileMetadata.confirmCreate")}</Button>}
          {metadata.recentJobs.isError && <Button variant="text" onClick={() => { void metadata.recentJobs.refetch(); }}>{t("retry")}</Button>}
          {metadata.jobId && <SpaceProcessingProgress scope={scope} spaceId={spaceId} jobId={metadata.jobId} kind="metadata_schema_change"
            onCompleted={metadata.handleCompleted} onStateChange={metadata.handleStateChange} />}
        </>}
        {error && <p role="alert">{error}</p>}
        {metadata.schema.isError && <Button variant="text" onClick={() => { void metadata.refetch(); }}>{t("retry")}</Button>}
      </fieldset>
      <DialogFooter>
        {view !== "values" && <Button variant="text" disabled={creating || uncertain} onClick={() => { setView(view === "create" ? "add" : "values"); setError(""); }}>{t("back")}</Button>}
        <Button variant="outlined" disabled={busy} onClick={onClose}>{t("cancel")}</Button>
        {view === "values" && <Button disabled={busy || Boolean(awaitingField) || !metadata.schema.isSuccess} onClick={() => { void handleSave(); }}>{t("save")}</Button>}
      </DialogFooter>
    </DialogContent>
  </Dialog>;
}
