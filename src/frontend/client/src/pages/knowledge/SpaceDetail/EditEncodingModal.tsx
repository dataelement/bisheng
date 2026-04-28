import { useEffect, useState } from "react";
import {
    Dialog,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Button,
    Input,
} from "~/components/ui";
import { useLocalize } from "~/hooks";
import { KnowledgeFile } from "~/api/knowledge";

interface EditEncodingModalProps {
    file: KnowledgeFile | null;
    open: boolean;
    onClose: () => void;
    onSubmit: (newEncoding: string) => Promise<void>;
}

export function EditEncodingModal({ file, open, onClose, onSubmit }: EditEncodingModalProps) {
    const localize = useLocalize();
    const [value, setValue] = useState<string>("");
    const [submitting, setSubmitting] = useState(false);

    useEffect(() => {
        if (open) {
            setValue(file?.fileEncoding ?? "");
        }
    }, [open, file?.fileEncoding]);

    const trimmed = value.trim();
    const error =
        !trimmed
            ? localize("com_knowledge.file_encoding_required")
            : trimmed.length > 64
                ? localize("com_knowledge.file_encoding_max_length")
                : "";

    const handleSubmit = async () => {
        if (error || submitting) return;
        setSubmitting(true);
        try {
            await onSubmit(trimmed);
            onClose();
        } finally {
            setSubmitting(false);
        }
    };

    return (
        <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>
                        {localize("com_knowledge.file_encoding_edit_title")}
                    </DialogTitle>
                </DialogHeader>
                <div className="space-y-2">
                    <Input
                        value={value}
                        onChange={(e) => setValue(e.target.value)}
                        placeholder={localize("com_knowledge.file_encoding_placeholder")}
                        maxLength={64}
                        autoFocus
                    />
                    {error && (
                        <p className="text-sm text-destructive">{error}</p>
                    )}
                </div>
                <DialogFooter>
                    <Button variant="outline" onClick={onClose} disabled={submitting}>
                        {localize("com_knowledge.cancel")}
                    </Button>
                    <Button
                        disabled={!!error || submitting}
                        onClick={handleSubmit}
                    >
                        {localize("com_knowledge.save")}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
