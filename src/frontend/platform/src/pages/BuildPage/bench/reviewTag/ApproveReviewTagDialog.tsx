import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { Label } from "@/components/bs-ui/label";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/bs-ui/select";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import {
    approveOrRejectReviewTagApi,
    getKnowledgeSpaceTagLibrariesApi,
    getKnowledgeSpaceTagLibrariesByKnowledgeApi,
    type KnowledgeSpaceTagLibraryListItem,
    type ReviewTagItem,
} from "@/controllers/API/knowledgeSpaceTagLibrary";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ReviewTagSimilarBanner } from "./ReviewTagSimilarBanner";
import { ReviewTagSimilarConfirmDialog } from "./ReviewTagSimilarConfirmDialog";
import { useReviewTagSimilarCheck } from "./useReviewTagSimilarCheck";

export interface ApproveReviewTagDialogProps {
    open: boolean;
    row: ReviewTagItem | null;
    knowledgeId: number | null;
    onOpenChange: (open: boolean) => void;
    onApproved: () => void;
}

export function ApproveReviewTagDialog({
    open,
    row,
    knowledgeId,
    onOpenChange,
    onApproved,
}: ApproveReviewTagDialogProps) {
    const { t } = useTranslation();
    const { toast } = useToast();
    const [libraries, setLibraries] = useState<KnowledgeSpaceTagLibraryListItem[]>([]);
    const [selectedLibraryId, setSelectedLibraryId] = useState("");
    const [loading, setLoading] = useState(false);
    const [saving, setSaving] = useState(false);
    const [usingAllLibraries, setUsingAllLibraries] = useState(false);
    const [similarConfirmOpen, setSimilarConfirmOpen] = useState(false);
    const { result: similarResult, loading: similarLoading, hasSimilar } = useReviewTagSimilarCheck(
        row?.tag_name,
        selectedLibraryId,
    );

    useEffect(() => {
        setSimilarConfirmOpen(false);
    }, [open, row?.tag_name, selectedLibraryId]);

    useEffect(() => {
        if (!open) {
            setSelectedLibraryId("");
            setLibraries([]);
            setUsingAllLibraries(false);
            return;
        }
        if (!knowledgeId) return;
        setLoading(true);
        const hasTagLibrary = row?.tag_library_id != null && row.tag_library_id > 0;
        const loadLibraries = async () => {
            if (hasTagLibrary) {
                const boundLibraries = await captureAndAlertRequestErrorHoc(
                    getKnowledgeSpaceTagLibrariesByKnowledgeApi(knowledgeId),
                );
                const normalizedBound = boundLibraries || [];
                if (normalizedBound.length > 0) {
                    setLibraries(normalizedBound);
                    setUsingAllLibraries(false);
                    return;
                }
            }
            const allLibrariesPage = await captureAndAlertRequestErrorHoc(
                getKnowledgeSpaceTagLibrariesApi({ page: 1, page_size: 500 }),
            );
            setLibraries(allLibrariesPage?.data || []);
            setUsingAllLibraries(true);
        };
        void loadLibraries().finally(() => {
            setLoading(false);
        });
    }, [open, knowledgeId, row?.tag_library_id]);

    const submitApprove = async (ackSimilar = false) => {
        if (!row?.tag_name || !knowledgeId || !selectedLibraryId) {
            toast({
                variant: "error",
                description: t("build.reviewTagSelectLibraryRequired", "请选择导入的标签库"),
            });
            return;
        }
        setSaving(true);
        const res = await captureAndAlertRequestErrorHoc(
            approveOrRejectReviewTagApi({
                tag_name: row.tag_name,
                status: 1,
                resource_type: row.resource_type || "",
                tag_library_id: Number(selectedLibraryId),
                knowledge_id: knowledgeId,
                ack_similar: ackSimilar,
            }),
        );
        setSaving(false);
        if (!res) return;
        toast({ variant: "success", description: t("build.approved", "已通过") });
        onOpenChange(false);
        onApproved();
    };

    const handleConfirm = () => {
        if (!row?.tag_name || !knowledgeId || !selectedLibraryId) {
            toast({
                variant: "error",
                description: t("build.reviewTagSelectLibraryRequired", "请选择导入的标签库"),
            });
            return;
        }
        if (hasSimilar) {
            setSimilarConfirmOpen(true);
            return;
        }
        void submitApprove();
    };

    const handleSimilarConfirm = () => {
        setSimilarConfirmOpen(false);
        void submitApprove(true);
    };

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="gap-0 p-0 sm:max-w-[480px] bg-background-login">
                <DialogHeader className="border-b border-[#EBECF0] px-6 py-4">
                    <DialogTitle>{t("build.reviewTagApproveTitle", "审核通过")}</DialogTitle>
                </DialogHeader>
                <div className="space-y-4 px-6 py-5">
                    <p className="text-sm text-muted-foreground">
                        {usingAllLibraries
                            ? t(
                                "build.reviewTagApproveDescAllLibraries",
                                "将标签「{{tagName}}」导入到租户下的标签库中",
                                { tagName: row?.tag_name || "" },
                            )
                            : t(
                                "build.reviewTagApproveDesc",
                                "将标签「{{tagName}}」导入到该知识空间绑定的标签库中",
                                { tagName: row?.tag_name || "" },
                            )}
                    </p>
                    <div>
                        <Label className="bisheng-label">
                            {t("build.reviewTagSelectLibrary", "选择标签库")}
                            <span className="bisheng-tip">*</span>
                        </Label>
                        <Select value={selectedLibraryId} onValueChange={setSelectedLibraryId} disabled={loading || saving}>
                            <SelectTrigger className="mt-2">
                                <SelectValue
                                    placeholder={
                                        loading
                                            ? t("loading")
                                            : t("build.reviewTagSelectLibraryPlaceholder", "请选择标签库")
                                    }
                                />
                            </SelectTrigger>
                            <SelectContent>
                                {libraries.map((library) => (
                                    <SelectItem key={library.id} value={String(library.id)}>
                                        {library.name}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                        {!loading && libraries.length === 0 && (
                            <p className="mt-2 text-xs text-muted-foreground">
                                {t("build.reviewTagNoLibraryAvailable", "当前租户暂无可用标签库")}
                            </p>
                        )}
                    </div>
                    {selectedLibraryId && (
                        <ReviewTagSimilarBanner result={similarResult} loading={similarLoading} />
                    )}
                </div>
                <DialogFooter className="border-t border-[#EBECF0] px-6 py-3">
                    <Button variant="outline" className="px-8" onClick={() => onOpenChange(false)}>
                        {t("cancel", { ns: "bs" })}
                    </Button>
                    <Button className="px-8" disabled={saving || loading || libraries.length === 0} onClick={handleConfirm}>
                        {hasSimilar
                            ? t("build.reviewTagProceedWithSimilar", "继续审核")
                            : t("confirm", { ns: "bs" })}
                    </Button>
                </DialogFooter>
            </DialogContent>
            <ReviewTagSimilarConfirmDialog
                open={similarConfirmOpen}
                tagName={row?.tag_name || ""}
                similarMatches={similarResult?.similar_matches ?? []}
                saving={saving}
                onOpenChange={setSimilarConfirmOpen}
                onConfirm={handleSimilarConfirm}
            />
        </Dialog>
    );
}
