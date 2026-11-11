import { useEffect, useState } from "react";
import { Button, Checkbox, Input } from "@bisheng/ui";
import { useTranslation } from "react-i18next";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/bs-ui/dialog";
interface BatchTagDraftDialogProps {
  spaceId: number;
  availableTags: { id: number; name: string }[];
  open: boolean;
  onClose: () => void;
  onReview: (ids: number[], names: string[]) => void;
}
export function BatchTagDraftDialog({
  spaceId,
  availableTags,
  open,
  onClose,
  onReview,
}: BatchTagDraftDialogProps) {
  const { t } = useTranslation("knowledge");
  const [tags, setTags] = useState<{ id: number; name: string }[]>([]);
  const [ids, setIds] = useState<number[]>([]),
    [names, setNames] = useState<string[]>([]),
    [name, setName] = useState("");
  useEffect(() => {
    if (!open) return;
    setIds([]);
    setNames([]);
    setName("");
    setTags([...new Map(availableTags.map((tag) => [tag.id, tag])).values()]);
    // Opening owns the tag draft; rerenders must not discard in-progress input.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, spaceId]);
  const add = () => {
    const value = name.trim();
    if (!value || value.length > 100) return;
    const existing = tags.find((tag) => tag.name === value);
    if (existing) setIds((old) => [...new Set([...old, existing.id])]);
    else setNames((old) => [...new Set([...old, value])]);
    setName("");
  };
  return (
    <Dialog
      open={open}
      onOpenChange={(value) => {
        if (!value) onClose();
      }}
    >
      <DialogContent aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>{t("batch.tag_title")}</DialogTitle>
        </DialogHeader>
        <p>{t("batch.draft_notice")}</p>
        <div className="max-h-60 overflow-y-auto space-y-2">
          {tags.map((tag) => (
            <Checkbox
              key={tag.id}
              label={tag.name}
              checked={ids.includes(tag.id)}
              onCheckedChange={(checked) =>
                setIds((old) =>
                  checked === true ? [...old, tag.id] : old.filter((id) => id !== tag.id),
                )
              }
            />
          ))}
          {names.map((value) => (
            <Checkbox
              key={value}
              label={value}
              checked
              onCheckedChange={() => setNames((old) => old.filter((name) => name !== value))}
            />
          ))}
        </div>
        <Input
          aria-label={t("batch.new_tag")}
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
        {name.length > 100 && <p role="alert">{t("batch.invalid_name")}</p>}
        <Button variant="text" disabled={!name.trim() || name.length > 100} onClick={add}>
          {t("batch.add_tag")}
        </Button>
        <DialogFooter>
          <Button variant="outlined" onClick={onClose}>
            {t("batch.cancel")}
          </Button>
          <Button
            disabled={(!ids.length && !names.length) || !!name.trim()}
            onClick={() => onReview(ids, names)}
          >
            {t("batch.review")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
