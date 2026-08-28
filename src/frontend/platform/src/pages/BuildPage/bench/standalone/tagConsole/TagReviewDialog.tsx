import { Button } from "@/components/bs-ui/button"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog"
import { Textarea } from "@/components/bs-ui/input"
import { Label } from "@/components/bs-ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import {
    getTagConsoleReviewDetailApi,
    type KnowledgeSpaceTagLibraryListItem,
    type TagConsoleReviewItem,
    type TagConsoleReviewRef,
} from "@/controllers/API/knowledgeSpaceTagLibrary"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { ReviewTagSimilarBanner } from "../../reviewTag/ReviewTagSimilarBanner"
import { ReviewTagSimilarConfirmDialog } from "../../reviewTag/ReviewTagSimilarConfirmDialog"
import { useReviewTagSimilarCheck } from "../../reviewTag/useReviewTagSimilarCheck"
import { SourceFileLinks } from "./SourceFileLinks"
import { tagSourceLabel } from "./TagSourceIcon"
import { useApprovableLibraries } from "./useApprovableLibraries"

interface TagReviewDialogProps {
    /** Null closes the dialog. */
    target: TagConsoleReviewRef | null
    /** Fallback list, used only while the tag's own source is still unknown. */
    libraries: KnowledgeSpaceTagLibraryListItem[]
    saving: boolean
    onClose: () => void
    onApprove: (libraryId: number, ackSimilar?: boolean) => void
    onReject: (reason: string) => void
}

/**
 * Single-tag review, replacing the old separate confirm/reject buttons.
 *
 * The read-only block exists because a reviewer looking at just a tag name
 * cannot tell whether to accept it — they need to see which file it came from.
 * Every source file is listed, not only the first, so the blast radius of an
 * approval is visible up front.
 */
export function TagReviewDialog({ target, libraries, saving, onClose, onApprove, onReject }: TagReviewDialogProps) {
    const { t } = useTranslation()
    const { toast } = useToast()
    const [detail, setDetail] = useState<TagConsoleReviewItem | null>(null)
    const [loading, setLoading] = useState(false)
    const [libraryId, setLibraryId] = useState("")
    const [rejectReason, setRejectReason] = useState("")
    const [similarConfirmOpen, setSimilarConfirmOpen] = useState(false)

    const { result: similarResult, loading: similarLoading, hasSimilar } = useReviewTagSimilarCheck(
        detail?.name,
        libraryId,
    )

    // Any public library in the tenant can receive the tag; approval binds
    // in-scope source knowledge spaces afterwards.
    const { libraries: approvable, loading: loadingLibraries } = useApprovableLibraries()
    const selectable = approvable.length ? approvable : libraries

    useEffect(() => {
        if (!target) {
            setDetail(null)
            return
        }
        setLibraryId("")
        setRejectReason("")
        setSimilarConfirmOpen(false)
        setLoading(true)
        captureAndAlertRequestErrorHoc(getTagConsoleReviewDetailApi(target)).then((res) => {
            if (res) {
                setDetail(res)
                if (res.library_id) setLibraryId(String(res.library_id))
            }
            setLoading(false)
        })
    }, [target])

    useEffect(() => {
        setSimilarConfirmOpen(false)
    }, [libraryId, detail?.name])

    const submitApprove = (ackSimilar = false) => {
        if (!libraryId) {
            toast({ variant: "error", description: t("build.reviewTagSelectLibraryRequired", "请选择导入的标签库") })
            return
        }
        onApprove(Number(libraryId), ackSimilar)
    }

    const handleApprove = () => {
        if (!libraryId) {
            toast({ variant: "error", description: t("build.reviewTagSelectLibraryRequired", "请选择导入的标签库") })
            return
        }
        if (hasSimilar) {
            setSimilarConfirmOpen(true)
            return
        }
        submitApprove()
    }

    const handleSimilarConfirm = () => {
        setSimilarConfirmOpen(false)
        submitApprove(true)
    }

    const handleReject = () => {
        if (!rejectReason.trim()) {
            toast({ variant: "error", description: t("build.tagConsole.rejectReasonRequired", "驳回原因不能为空") })
            return
        }
        onReject(rejectReason.trim())
    }

    const field = (label: string, value: React.ReactNode) => (
        <div className="flex gap-2 py-1 text-sm">
            <span className="w-24 shrink-0 text-muted-foreground">{label}</span>
            <span className="min-w-0 flex-1">{value}</span>
        </div>
    )

    return (
        <Dialog open={Boolean(target)} onOpenChange={(open) => !open && onClose()}>
            <DialogContent className="gap-0 p-0 sm:max-w-[640px] bg-background-login">
                <DialogHeader className="border-b border-[#EBECF0] px-6 py-4">
                    <DialogTitle>{t("build.tagConsole.reviewTitle", "标签审核")}</DialogTitle>
                </DialogHeader>

                <div className="space-y-4 px-6 py-5">
                    {loading ? (
                        <p className="py-6 text-center text-sm text-muted-foreground">{t("loading")}</p>
                    ) : (
                        <>
                            <div className="rounded-lg border border-[#ECECEC] bg-[#FAFBFC] p-4">
                                {field(t("build.tagName", "标签名称"), detail?.name || "-")}
                                {field(
                                    t("build.tagConsole.tagType", "标签类型"),
                                    detail ? tagSourceLabel(detail.resource_type, t) : "-",
                                )}
                                {field(t("build.creator", "创建者"), detail?.submitter_name || "-")}
                                {field(t("build.tagConsole.libraryName", "所属标签库"), detail?.library_name || "-")}
                                {field(
                                    t("build.tagConsole.sourceKnowledge", "标签来源知识"),
                                    <SourceFileLinks files={detail?.source_files || []} max={10} />,
                                )}
                            </div>

                            <div>
                                <Label className="bisheng-label">
                                    {t("build.reviewTagSelectLibrary", "选择标签库")}
                                    <span className="bisheng-tip">*</span>
                                </Label>
                                <Select value={libraryId} onValueChange={setLibraryId} disabled={loadingLibraries}>
                                    <SelectTrigger className="mt-2">
                                        <SelectValue
                                            placeholder={t("build.reviewTagSelectLibraryPlaceholder", "请选择标签库")}
                                        />
                                    </SelectTrigger>
                                    <SelectContent>
                                        {selectable.map((library) => (
                                            <SelectItem key={library.id} value={String(library.id)}>
                                                {library.name}
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            </div>
                            {libraryId && (
                                <ReviewTagSimilarBanner result={similarResult} loading={similarLoading} />
                            )}

                            <div>
                                <Label className="bisheng-label">{t("build.tagConsole.rejectReason", "驳回原因")}</Label>
                                <Textarea
                                    className="mt-2 min-h-20"
                                    value={rejectReason}
                                    maxLength={256}
                                    placeholder={t("build.tagConsole.rejectReasonPlaceholder", "请填写驳回原因")}
                                    onChange={(e) => setRejectReason(e.target.value)}
                                />
                            </div>
                        </>
                    )}
                </div>

                <DialogFooter className="border-t border-[#EBECF0] px-6 py-3">
                    <Button variant="outline" className="px-8" onClick={onClose}>
                        {t("cancel", { ns: "bs" })}
                    </Button>
                    <Button variant="destructive" className="px-8" disabled={saving || loading} onClick={handleReject}>
                        {t("build.tagConsole.reject", "驳回")}
                    </Button>
                    <Button className="px-8" disabled={saving || loading} onClick={handleApprove}>
                        {hasSimilar
                            ? t("build.reviewTagProceedWithSimilar", "继续审核")
                            : t("build.tagConsole.approve", "同意")}
                    </Button>
                </DialogFooter>
            </DialogContent>
            <ReviewTagSimilarConfirmDialog
                open={similarConfirmOpen}
                tagName={detail?.name || ""}
                similarMatches={similarResult?.similar_matches ?? []}
                saving={saving}
                onOpenChange={setSimilarConfirmOpen}
                onConfirm={handleSimilarConfirm}
            />
        </Dialog>
    )
}
