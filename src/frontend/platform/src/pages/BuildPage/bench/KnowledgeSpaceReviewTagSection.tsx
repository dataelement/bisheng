import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { SearchInput } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/bs-ui/select";
import { Switch } from "@/components/bs-ui/switch";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import {
    approveOrRejectReviewTagApi,
    getKnowledgeSpaceReviewTagListApi,
    getKnowledgeSpaceTagLibrariesByKnowledgeApi,
    type KnowledgeSpaceTagLibraryListItem,
    type ReviewTagItem,
} from "@/controllers/API/knowledgeSpaceTagLibrary";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { Check, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

const PAGE_SIZE = 5;

interface KnowledgeSpaceTagSectionProps {
    visible: boolean;
    onToggle: (visible: boolean) => void;
}

interface ApproveReviewTagDialogProps {
    open: boolean;
    row: ReviewTagItem | null;
    knowledgeId: number | null;
    onOpenChange: (open: boolean) => void;
    onApproved: () => void;
}

function formatTagSourceLabel(resourceType: string, t: (key: string, defaultValue: string) => string) {
    if (resourceType === "ai_auto_tag") {
        return t("build.tagSourceAi", "AI标签");
    }
    if (resourceType === "system_tag") {
        return t("build.tagSourceSystem", "系统标签");
    }
    return t("build.tagSourceManual", "人工标签");
}

function ApproveReviewTagDialog({
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

    useEffect(() => {
        if (!open) {
            setSelectedLibraryId("");
            setLibraries([]);
            return;
        }
        if (!knowledgeId) return;
        setLoading(true);
        captureAndAlertRequestErrorHoc(getKnowledgeSpaceTagLibrariesByKnowledgeApi(knowledgeId)).then((res) => {
            setLibraries(res || []);
            setLoading(false);
        });
    }, [open, knowledgeId]);

    const handleConfirm = async () => {
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
            }),
        );
        setSaving(false);
        if (!res) return;
        toast({ variant: "success", description: t("build.approved", "已通过") });
        onOpenChange(false);
        onApproved();
    };

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="gap-0 p-0 sm:max-w-[480px] bg-background-login">
                <DialogHeader className="border-b border-[#EBECF0] px-6 py-4">
                    <DialogTitle>{t("build.reviewTagApproveTitle", "审核通过")}</DialogTitle>
                </DialogHeader>
                <div className="space-y-4 px-6 py-5">
                    <p className="text-sm text-muted-foreground">
                        {t(
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
                                {t("build.reviewTagNoBoundLibrary", "该知识空间尚未绑定标签库")}
                            </p>
                        )}
                    </div>
                </div>
                <DialogFooter className="border-t border-[#EBECF0] px-6 py-3">
                    <Button variant="outline" className="px-8" onClick={() => onOpenChange(false)}>
                        {t("cancel", { ns: "bs" })}
                    </Button>
                    <Button className="px-8" disabled={saving || loading || libraries.length === 0} onClick={handleConfirm}>
                        {t("confirm", { ns: "bs" })}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}

export default function KnowledgeSpaceReviewTagSection({
    visible,
    onToggle,
}: KnowledgeSpaceTagSectionProps) {
    const { t } = useTranslation();
    const { toast } = useToast();
    const [keyword, setKeyword] = useState("");
    const [rows, setRows] = useState<ReviewTagItem[]>([]);
    const [loading, setLoading] = useState(false);
    const [page, setPage] = useState(1);
    const [total, setTotal] = useState(0);
    const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
    const [approveDialogOpen, setApproveDialogOpen] = useState(false);
    const [approveTarget, setApproveTarget] = useState<ReviewTagItem | null>(null);
    const [approveKnowledgeId, setApproveKnowledgeId] = useState<number | null>(null);

    const loadData = useCallback(async (targetPage: number) => {
        setLoading(true);
        const res = await captureAndAlertRequestErrorHoc(
            getKnowledgeSpaceReviewTagListApi({
                page: targetPage,
                page_size: PAGE_SIZE,
                keyword: keyword.trim() || undefined,
            }),
        );
        if (res) {
            setRows(res.data || []);
            setTotal(res.total || 0);
        }
        setLoading(false);
    }, [keyword]);

    useEffect(() => {
        setPage(1);
        loadData(1);
    }, [loadData]);

    const handlePageChange = (newPage: number) => {
        setPage(newPage);
        loadData(newPage);
    };

    const openApproveDialog = (row: ReviewTagItem, knowledgeId?: number | null) => {
        const resolvedKnowledgeId =
            knowledgeId ??
            row.resource_files?.find((file) => file.knowledge_id)?.knowledge_id ??
            row.knowledge_ids?.[0] ??
            null;
        if (!resolvedKnowledgeId) {
            toast({
                variant: "error",
                description: t("build.reviewTagMissingKnowledge", "无法确定标签所属知识空间"),
            });
            return;
        }
        setApproveTarget(row);
        setApproveKnowledgeId(resolvedKnowledgeId);
        setApproveDialogOpen(true);
    };

    const handleReject = async (row: ReviewTagItem) => {
        if (!row.tag_name?.length) return;
        const res = await captureAndAlertRequestErrorHoc(
            approveOrRejectReviewTagApi({ tag_name: row.tag_name || "", status: 2, resource_type: row.resource_type || "" }),
        );
        if (res) {
            toast({ variant: "success", description: t("build.rejected", "已拒绝") });
            loadData(page);
        }
    };

    const renderActions = (row: ReviewTagItem, knowledgeId?: number | null) => (
        <div className="flex items-center gap-1">
            <Button variant="ghost" size="sm" onClick={() => openApproveDialog(row, knowledgeId)}>
                <Check className="mr-1 size-4" />
            </Button>
            <Button variant="ghost" size="sm" onClick={() => handleReject(row)}>
                <X className="mr-1 size-4" />
            </Button>
        </div>
    );

    return (
        <div className="p-5 rounded-lg">
            <div className="border-t border-[#ECECEC] pt-6">
                <div className="flex items-center justify-between gap-4">
                    <div>
                        <p className="text-lg font-bold">
                            {t("build.autoTagGenerationTitle", "待审核标签")}
                            <span className="text-[#86909C] text-sm">
                                {`（${total}）`}
                            </span>
                        </p>
                        <p className="mt-1 text-sm text-[#86909C]">
                            {t(
                                "build.autoTagGenerationDesc",
                                "审核AI打标推荐、词表中尚不存在的标签名；采纳后写入词表并挂到对应知识。",
                            )}
                        </p>
                    </div>
                    <Switch checked={visible} onCheckedChange={onToggle} />
                </div>

                <div className="mt-4 rounded-lg border border-[#ECECEC] bg-[#FAFBFC] p-4">
                        <div className="mb-3 flex items-center gap-2">
                            <SearchInput
                                className="w-[280px]"
                                placeholder={t("build.searchReviewTag", "搜索待审核标签")}
                                value={keyword}
                                onChange={(e) => setKeyword(e.target.value)}
                            />
                        </div>
                        <div className="max-h-[240px] overflow-y-auto rounded-md border bg-background">
                            <table className="w-full table-fixed border-collapse">
                                <thead className="sticky top-0 z-10 bg-background">
                                    <tr className="text-left text-sm text-muted-foreground">
                                        <th className="w-[20%] px-4 py-3 font-medium">
                                            {t("build.reviewTagName", "建议标签")}
                                        </th>
                                        <th className="w-[20%] px-4 py-3 font-medium">
                                            {t("build.reviewTagSource", "标签来源")}
                                        </th>
                                        <th className="w-[40%] px-4 py-3 font-medium">
                                            {t("build.fileResource", "文件来源")}
                                        </th>
                                        <th className="w-[20%] px-4 py-3 font-medium">
                                            {t("build.submitTime", "提交时间")}
                                        </th>
                                        <th className="w-[20%] px-4 py-3 font-medium">
                                            {t("build.operation", "操作")}
                                        </th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {loading ? (
                                        <tr>
                                            <td className="px-4 py-10 text-center text-sm text-muted-foreground" colSpan={5}>
                                                {t("loading")}
                                            </td>
                                        </tr>
                                    ) : rows.length === 0 ? (
                                        <tr>
                                            <td className="px-4 py-10 text-center text-sm text-muted-foreground" colSpan={5}>
                                                {t("build.tagEmpty", "暂无待审核标签")}
                                            </td>
                                        </tr>
                                    ) : (
                                        rows.map((group) => {
                                            if (!group.resource_files || group.resource_files.length === 0) {
                                                return (
                                                    <tr key={group.tag_name} className="border-t text-sm">
                                                        <td className="truncate px-4 py-3 font-medium">{group.tag_name}</td>
                                                        <td className="truncate px-4 py-3 font-medium">
                                                            {formatTagSourceLabel(group.resource_type, t)}
                                                        </td>
                                                        <td className="truncate px-4 py-3 text-muted-foreground">-</td>
                                                        <td className="px-4 py-3 text-muted-foreground">-</td>
                                                        <td className="px-4 py-3">
                                                            {renderActions(group, group.knowledge_ids?.[0] ?? null)}
                                                        </td>
                                                    </tr>
                                                );
                                            }
                                            return group.resource_files.map((resource, idx) => (
                                                <tr key={`${group.tag_name}-${idx}`} className="border-t text-sm">
                                                    {idx === 0 && (
                                                        <td rowSpan={group.resource_files.length} className="truncate px-4 py-3 font-medium align-top">
                                                            {group.tag_name}
                                                        </td>
                                                    )}
                                                    {idx === 0 && (
                                                        <td rowSpan={group.resource_files.length} className="truncate px-4 py-3 font-medium align-top">
                                                            {formatTagSourceLabel(group.resource_type, t)}
                                                        </td>
                                                    )}
                                                    <td className="truncate px-4 py-3">
                                                        {resource.file_url ? (
                                                            <a
                                                                href={resource.file_url}
                                                                target="_blank"
                                                                rel="noopener noreferrer"
                                                                className="text-blue-600 hover:underline"
                                                            >
                                                                {resource.file_name || "-"}
                                                            </a>
                                                        ) : (
                                                            resource.file_name || "-"
                                                        )}
                                                    </td>
                                                    <td className="px-4 py-3">{resource.submit_time || "-"}</td>
                                                    <td className="px-4 py-3">
                                                        {renderActions(group, resource.knowledge_id ?? null)}
                                                    </td>
                                                </tr>
                                            ));
                                        })
                                    )}
                                </tbody>
                            </table>
                        </div>
                        {rows.length > 0 && (
                            <div className="mt-2 flex items-center justify-end gap-2">
                                <Button
                                    variant="outline"
                                    size="sm"
                                    disabled={page <= 1}
                                    onClick={() => handlePageChange(page - 1)}
                                >
                                    {t("build.prevPage", "上一页")}
                                </Button>
                                <span className="text-sm text-muted-foreground">
                                    {page} / {totalPages}
                                </span>
                                <Button
                                    variant="outline"
                                    size="sm"
                                    disabled={page >= totalPages}
                                    onClick={() => handlePageChange(page + 1)}
                                >
                                    {t("build.nextPage", "下一页")}
                                </Button>
                            </div>
                        )}
                </div>
            </div>

            <ApproveReviewTagDialog
                open={approveDialogOpen}
                row={approveTarget}
                knowledgeId={approveKnowledgeId}
                onOpenChange={setApproveDialogOpen}
                onApproved={() => loadData(page)}
            />
        </div>
    );
}
