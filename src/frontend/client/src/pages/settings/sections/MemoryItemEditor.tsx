import { Button, Modal, Textarea } from "@bisheng/ui";
import { useEffect, useState } from "react";
import { memoryErrorMessage, type MemoryItemInput } from "~/api/memory";
import { useLocalize } from "~/hooks";

/** Soft limit mirrored from the backend rule (AC-89); the backend still decides. */
const CONTENT_LIMIT = 200;

interface MemoryItemEditorProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Rejects with the backend reason; the dialog stays open and shows it. */
  onSubmit: (input: MemoryItemInput) => Promise<unknown>;
}

/**
 * Add a memory: one box for what to remember (AC-89). Existing memories are not
 * edited by hand; they are changed by telling the AI how, on the memory's own view.
 * A rejection keeps the typed text and shows why.
 */
export function MemoryItemEditor({ open, onOpenChange, onSubmit }: MemoryItemEditorProps) {
  const localize = useLocalize();
  const [content, setContent] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  // Start empty each time the dialog opens, never while the user types.
  useEffect(() => {
    if (!open) return;
    setContent("");
    setError("");
    setSaving(false);
  }, [open]);

  const handleSave = async () => {
    setSaving(true);
    setError("");
    try {
      await onSubmit({ content: content.trim(), type: "fact", event_time: null });
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
      title={localize("memory.add_title")}
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
      <div className="flex flex-col gap-2">
        <Textarea
          aria-label={localize("memory.add_title")}
          value={content}
          onChange={(e) => setContent(e.target.value)}
          maxLength={CONTENT_LIMIT}
          showCount
          status={error ? "error" : "default"}
          placeholder={localize("memory.content_placeholder")}
          className="min-h-[96px]"
        />
        {error && (
          <p role="alert" className="text-body-sm text-danger">
            {error}
          </p>
        )}
      </div>
    </Modal>
  );
}
