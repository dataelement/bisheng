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
import { batchUpdateFileCategoryApi } from "~/api/knowledge";
import type { PortalFileCategoryGroupOption, PortalFileSubcategoryOption } from "../portal/types";
import { PortalFileCategoryDropdown } from "../portal/components/PortalFileCategoryDropdown";

interface BatchCategoryModalProps {
    open: boolean;
    onClose: () => void;
    spaceId: string;
    fileIds: string[];
    fileCategoryGroups: PortalFileCategoryGroupOption[];
    onSaved?: () => void;
}

/** Batch-update the classification (category / subcategory) of the selected files. */
export function BatchCategoryModal({
    open,
    onClose,
    spaceId,
    fileIds,
    fileCategoryGroups,
    onSaved,
}: BatchCategoryModalProps) {
    const localize = useLocalize();
    const { showToast } = useToastContext();
    const [selected, setSelected] = useState<PortalFileSubcategoryOption | null>(null);
    const [submitting, setSubmitting] = useState(false);

    const handleClose = () => {
        if (submitting) return;
        setSelected(null);
        onClose();
    };

    const handleSubmit = async () => {
        if (!selected || submitting || fileIds.length === 0) return;
        setSubmitting(true);
        try {
            const result = await batchUpdateFileCategoryApi(spaceId, {
                file_ids: fileIds.map(Number),
                file_category_code: selected.parentCode,
                file_subcategory_code: selected.code,
            });
            if (result.skipped.length > 0) {
                showToast({
                    message: localize("com_knowledge.batch_classification_partial_skip", {
                        count: result.skipped.length,
                    }),
                    status: "warning",
                });
            } else {
                showToast({ message: localize("com_knowledge.batch_category_success"), status: "success" });
            }
            onSaved?.();
            setSelected(null);
            onClose();
        } catch {
            showToast({ message: localize("com_knowledge.batch_category_failed"), status: "error" });
        } finally {
            setSubmitting(false);
        }
    };

    return (
        <Dialog open={open} onOpenChange={(o) => !o && handleClose()}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>{localize("com_knowledge.batch_category_title")}</DialogTitle>
                </DialogHeader>
                <div className="py-2">
                    <PortalFileCategoryDropdown
                        groups={fileCategoryGroups}
                        value={selected?.code}
                        ariaLabel={localize("com_knowledge.batch_category_title")}
                        onChange={(option) => setSelected(option)}
                    />
                </div>
                <DialogFooter>
                    <Button variant="outline" onClick={handleClose} disabled={submitting}>
                        {localize("com_knowledge.cancel")}
                    </Button>
                    <Button disabled={!selected || submitting} onClick={handleSubmit}>
                        {localize("com_knowledge.save")}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
