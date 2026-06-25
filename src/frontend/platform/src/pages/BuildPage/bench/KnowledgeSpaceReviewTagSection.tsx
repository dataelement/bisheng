import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Button } from "@/components/bs-ui/button";
import { Switch } from "@/components/bs-ui/switch";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import {
    getKnowledgeSpaceReviewTagListApi,
    approveOrRejectReviewTagApi,
    deleteReviewTagApi,
    type ReviewTagItem,
} from "@/controllers/API/knowledgeSpaceTagLibrary";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { Check, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

const PAGE_SIZE = 5;

interface KnowledgeSpaceTagSectionProps {
    visible: boolean;
    onToggle: (visible: boolean) => void;
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
    const [hasMore, setHasMore] = useState(false);
    const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

    const loadData = useCallback(async (targetPage: number) => {
        setLoading(true);
        const res = await captureAndAlertRequestErrorHoc(
            getKnowledgeSpaceReviewTagListApi({ page: targetPage, page_size: PAGE_SIZE }),
        );
        if (res) {
            setRows(res.data || []);
            setTotal(res.total || 0);
            setHasMore((res.data || []).length === PAGE_SIZE);
        }
        setLoading(false);
    }, []);

    useEffect(() => {
        if (visible) {
            setPage(1);
            loadData(1);
        }
    }, [visible, loadData]);

    const filteredRows = useMemo(() => {
        const trimmed = (keyword || '').trim().toLowerCase();
        if (!trimmed) return rows;
        return rows.filter((row) => (row.tag || '').toLowerCase().includes(trimmed));
    }, [rows, keyword]);

    const handlePageChange = (newPage: number) => {
        setPage(newPage);
        loadData(newPage);
    };

    const handleApprove = async (row: ReviewTagItem) => {
        if (!row.tag_name?.length) return;
        const res = await captureAndAlertRequestErrorHoc(
            approveOrRejectReviewTagApi({ tag_name: row.tag_name || '', status: 1, resource_type: row.resource_type || '' }),
        );
        if (res) {
            toast({ variant: "success", description: t("build.approved", "已通过") });
            loadData(page);
        }
    };

    const handleReject = async (row: ReviewTagItem) => {
        if (!row.tag_name?.length) return;
        const res = await captureAndAlertRequestErrorHoc(
            approveOrRejectReviewTagApi({ tag_name: row.tag_name || '', status: 2, resource_type: row.resource_type || '' }),
        );
        if (res) {
            toast({ variant: "success", description: t("build.rejected", "已拒绝") });
            loadData(page);
        }
    };

    const handleDelete = async (row: ReviewTagItem) => {
        if (!row.tag_name?.length) return;
        bsConfirm({
            title: t("build.deleteTagTitle", "删除标签"),
            desc: t("build.deleteReviewTagDesc", "确认删除该待审核标签？"),
            showClose: true,
            okTxt: t("build.confirmDelete", "确认删除"),
            canelTxt: t("cancel", { ns: "bs" }),
            async onOk(next) {
                const res = await captureAndAlertRequestErrorHoc(
                    deleteReviewTagApi({ tag_name: row.tag_name || '', resource_type: row.resource_type || '' }),
                );
                if (res) {
                    toast({ variant: "success", description: t("build.deleted", "已删除") });
                    loadData(page);
                }
                next?.();
            },
        });
    };

    return (
        <div className="p-5 rounded-lg">
            <div className="border-t border-[#ECECEC] pt-6">
                <div className="flex items-center justify-between gap-4">
                    <div>
                        <p className="text-lg font-bold">
                            {t("build.autoTagGenerationTitle", "待审核标签")}
                            {visible && (
                                <span className="text-[#86909C] text-sm">
                                    {`（${total}）`}
                                </span>
                            )}
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

                {visible && (
                    <div className="mt-4 rounded-lg border border-[#ECECEC] bg-[#FAFBFC] p-4">
                        <div className="max-h-[240px] overflow-y-auto rounded-md border bg-background">
                            <table className="w-full table-fixed border-collapse">
                                <thead className="bg-muted/40">
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
                                            <td className="px-4 py-10 text-center text-sm text-muted-foreground" colSpan={4}>
                                                {t("loading")}
                                            </td>
                                        </tr>
                                    ) : filteredRows.length === 0 ? (
                                        <tr>
                                            <td className="px-4 py-10 text-center text-sm text-muted-foreground" colSpan={4}>
                                                {t("build.tagEmpty", "暂无待审核标签")}
                                            </td>
                                        </tr>
                                    ) : (
                                        filteredRows.map((group) => {
                                            if (!group.resource_files || group.resource_files.length === 0) {
                                                return (
                                                    <tr key={group.tag_name} className="border-t text-sm">
                                                        <td className="truncate px-4 py-3 font-medium">{group.tag_name}</td>
                                                        <td className="truncate px-4 py-3 font-medium">{group.resource_type === "system_tag" ? "系统标签" : (group.resource_type === "ai_auto_tag" ? "AI标签" : "人工标签")}</td>
                                                        <td className="truncate px-4 py-3 text-muted-foreground">-</td>
                                                        <td className="px-4 py-3 text-muted-foreground">-</td>
                                                        <td className="px-4 py-3">
                                                            <div className="flex items-center gap-1">
                                                                <Button variant="ghost" size="sm" onClick={() => handleApprove(group)}>
                                                                    <Check className="mr-1 size-4" />
                                                                </Button>
                                                                <Button variant="ghost" size="sm" onClick={() => handleReject(group)}>
                                                                    <X className="mr-1 size-4" />
                                                                </Button>
                                                                {/* <Button variant="ghost" size="sm" onClick={() => handleDelete(group)}>
                                                                    <Trash2 className="mr-1 size-4" />
                                                                </Button> */}
                                                            </div>
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
                                                            {group.resource_type === "system_tag" ? "系统标签" : (group.resource_type === "ai_auto_tag" ? "AI标签" : "人工标签")}
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
                                                    {idx === 0 && (
                                                        <td rowSpan={group.resource_files.length} className="px-4 py-3 align-top">
                                                            <div className="flex items-center gap-1">
                                                                <Button variant="ghost" size="sm" onClick={() => handleApprove(group)}>
                                                                    <Check className="mr-1 size-4" />
                                                                </Button>
                                                                <Button variant="ghost" size="sm" onClick={() => handleReject(group)}>
                                                                    <X className="mr-1 size-4" />
                                                                </Button>
                                                                {/* <Button variant="ghost" size="sm" onClick={() => handleDelete(group)}>
                                                                    <Trash2 className="mr-1 size-4" />
                                                                </Button> */}
                                                            </div>
                                                        </td>
                                                    )}
                                                </tr>
                                            ));
                                        })
                                    )}
                                </tbody>
                            </table>
                        </div>
                        {filteredRows.length > 0 && (
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
                )}
            </div>
        </div>
    );
}
