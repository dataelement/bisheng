import { useState } from "react";
import {
    Dialog,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Button,
} from "~/components/ui";
import { useLocalize } from "~/hooks";
import { useToastContext } from "~/Providers";
import { batchUpdateFileBusinessDomainApi } from "~/api/knowledge";
import type { BusinessDomainOptionItem } from "../portal/uploadMetadata";

interface BatchBusinessDomainModalProps {
    open: boolean;
    onClose: () => void;
    spaceId: string;
    fileIds: string[];
    businessDomainOptions: BusinessDomainOptionItem[];
    onSaved?: () => void;
}

/** Batch-update the business domain of the selected files. */
export function BatchBusinessDomainModal({
    open,
    onClose,
    spaceId,
    fileIds,
    businessDomainOptions,
    onSaved,
}: BatchBusinessDomainModalProps) {
    const localize = useLocalize();
    const { showToast } = useToastContext();
    const [code, setCode] = useState<string>("");
    const [submitting, setSubmitting] = useState(false);

    const handleClose = () => {
        if (submitting) return;
        setCode("");
        onClose();
    };

    const handleSubmit = async () => {
        if (!code || submitting || fileIds.length === 0) return;
        setSubmitting(true);
        try {
            const result = await batchUpdateFileBusinessDomainApi(spaceId, {
                file_ids: fileIds.map(Number),
                business_domain_code: code,
            });
            if (result.skipped.length > 0) {
                showToast({
                    message: localize("com_knowledge.batch_classification_partial_skip", {
                        count: result.skipped.length,
                    }),
                    status: "warning",
                });
            } else {
                showToast({ message: localize("com_knowledge.batch_business_domain_success"), status: "success" });
            }
            onSaved?.();
            setCode("");
            onClose();
        } catch {
            showToast({ message: localize("com_knowledge.batch_business_domain_failed"), status: "error" });
        } finally {
            setSubmitting(false);
        }
    };

    return (
        <Dialog open={open} onOpenChange={(o) => !o && handleClose()}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>{localize("com_knowledge.batch_business_domain_title")}</DialogTitle>
                </DialogHeader>
                <div className="py-2">
                    <select
                        className="w-full rounded-[8px] border border-[#EBECF0] bg-white px-3 py-2 text-[14px] text-[#212121] focus:border-primary focus:outline-none"
                        value={code}
                        onChange={(e) => setCode(e.target.value)}
                        aria-label={localize("com_knowledge.batch_business_domain_title")}
                    >
                        <option value="" disabled>
                            --
                        </option>
                        {businessDomainOptions.map((option) => (
                            <option key={option.code} value={option.code}>
                                {option.name}
                            </option>
                        ))}
                    </select>
                </div>
                <DialogFooter>
                    <Button variant="outline" onClick={handleClose} disabled={submitting}>
                        {localize("com_knowledge.cancel")}
                    </Button>
                    <Button disabled={!code || submitting} onClick={handleSubmit}>
                        {localize("com_knowledge.save")}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
