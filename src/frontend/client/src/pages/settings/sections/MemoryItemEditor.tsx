import { Button, Input, Modal, Segmented, Textarea } from "@bisheng/ui";
import { useEffect, useId, useState } from "react";
import { memoryErrorMessage, type MemoryItem, type MemoryItemInput } from "~/api/memory";
import { MEMORY_ITEM_TYPES } from "~/components/Memory/memoryLabels";
import { useLocalize } from "~/hooks";

/** Soft limit mirrored from the backend rule (AC-89); the backend still decides. */
const CONTENT_LIMIT = 200;

interface MemoryItemEditorProps {
  open: boolean;
  /** The item being edited; omitted when adding. */
  item?: MemoryItem | null;
  onOpenChange: (open: boolean) => void;
  /** Rejects with the backend reason; the dialog stays open and shows it. */
  onSubmit: (input: MemoryItemInput) => Promise<unknown>;
}

/** Add / edit dialog. A rejection keeps the typed text and shows why (AC-89). */
export function MemoryItemEditor({ open, item, onOpenChange, onSubmit }: MemoryItemEditorProps) {
  const localize = useLocalize();
  const contentId = useId();
  const dateId = useId();
  const [content, setContent] = useState("");
  const [type, setType] = useState<string>("fact");
  const [eventTime, setEventTime] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  // Seed the form each time the dialog opens, never while the user types.
  useEffect(() => {
    if (!open) return;
    setContent(item?.content ?? "");
    setType(item?.type && (MEMORY_ITEM_TYPES as readonly string[]).includes(item.type) ? item.type : "fact");
    setEventTime(item?.event_time ?? "");
    setError("");
    setSaving(false);
  }, [open, item]);

  const handleSave = async () => {
    setSaving(true);
    setError("");
    try {
      await onSubmit({ content: content.trim(), type, event_time: eventTime || null });
      onOpenChange(false);
    } catch (err) {
      setError(memoryErrorMessage(err, localize("memory.save_failed")));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title={localize(item ? "memory.edit_title" : "memory.add_title")}
      closeLabel={localize("memory.close")}
      submitting={saving}
      footer={
        <>
          <Button variant="outlined" onClick={() => onOpenChange(false)} disabled={saving}>
            {localize("memory.cancel")}
          </Button>
          <Button onClick={handleSave} loading={saving} disabled={!content.trim()}>
            {localize("memory.save")}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-1.5">
          <label htmlFor={contentId} className="text-body-sm text-text-2">
            {localize("memory.field.content")}
          </label>
          <Textarea
            id={contentId}
            value={content}
            onChange={(e) => setContent(e.target.value)}
            maxLength={CONTENT_LIMIT}
            showCount
            status={error ? "error" : "default"}
            placeholder={localize("memory.content_placeholder")}
            className="min-h-[96px]"
          />
          {item?.has_detail && <span className="text-caption text-text-3">{localize("memory.edit_keeps_full_text")}</span>}
        </div>
        <div className="flex flex-col gap-1.5">
          <span className="text-body-sm text-text-2">{localize("memory.field.type")}</span>
          <Segmented
            aria-label={localize("memory.field.type")}
            value={type}
            onChange={setType}
            options={MEMORY_ITEM_TYPES.map((value) => ({ value, label: localize(`memory.type.${value}`) }))}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <label htmlFor={dateId} className="text-body-sm text-text-2">
            {localize("memory.field.event_time")}
          </label>
          <Input
            id={dateId}
            type="date"
            value={eventTime}
            onChange={(e) => setEventTime(e.target.value)}
            className="w-48"
          />
          <span className="text-caption text-text-3">{localize("memory.event_time_hint")}</span>
        </div>
        {error && (
          <p role="alert" className="text-body-sm text-danger">
            {error}
          </p>
        )}
      </div>
    </Modal>
  );
}
