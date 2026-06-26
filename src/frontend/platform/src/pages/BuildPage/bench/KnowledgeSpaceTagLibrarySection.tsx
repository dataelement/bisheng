import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { Input, SearchInput, Textarea } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { Switch } from "@/components/bs-ui/switch";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import {
    createKnowledgeSpaceTagLibraryApi,
    deleteKnowledgeSpaceTagLibraryApi,
    deleteKnowledgeSpaceTagApi,
    getKnowledgeSpaceTagLibrariesApi,
    getKnowledgeSpaceTagListApi,
    getKnowledgeSpaceTagLibraryApi,
    getKnowledgeSpaceTagLibraryUsageApi,
    updateKnowledgeSpaceTagLibraryApi,
    updateKnowledgeSpaceTagApi,
    createKnowledgeSpaceTagApi,
    type KnowledgeSpaceTagLibraryDetail,
    type KnowledgeSpaceTagLibraryListItem,
    type KnowledgeSpaceTagListItem,
    type KnowledgeSpaceTagDetail,
} from "@/controllers/API/knowledgeSpaceTagLibrary";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { Pencil, Plus, Trash2, Upload } from "lucide-react";
import type { ChangeEvent } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

const LIST_PAGE_SIZE = 200;
const TAG_LIMIT = 200;

interface KnowledgeSpaceTagLibrarySectionProps {
    visible: boolean;
    onToggle: (visible: boolean) => void;
}

interface KnowledgeSpaceTagSectionProps {
    visible: boolean;
    onToggle: (visible: boolean) => void;
}

interface TagDialogProps {
    open: boolean;
    mode: "create" | "edit";
    initial?: KnowledgeSpaceTagDetail | null;
    onOpenChange: (open: boolean) => void;
    onSaved: () => void;
}


interface TagLibraryDialogProps {
    open: boolean;
    mode: "create" | "edit";
    initial?: KnowledgeSpaceTagLibraryDetail | null;
    onOpenChange: (open: boolean) => void;
    onSaved: () => void;
}

function parseTags(text: string) {
    return text
        .split(/\r?\n/)
        .map((tag) => tag.trim())
        .filter(Boolean);
}

function TagLibraryDialog({ open, mode, initial, onOpenChange, onSaved }: TagLibraryDialogProps) {
    const { t } = useTranslation();
    const { toast } = useToast();
    const fileInputId = useRef(`tag-library-txt-${Math.random().toString(36).slice(2)}`).current;
    const [name, setName] = useState("");
    const [description, setDescription] = useState("");
    const [tagsText, setTagsText] = useState("");
    const [saving, setSaving] = useState(false);
    const tags = useMemo(() => parseTags(tagsText), [tagsText]);

    useEffect(() => {
        if (!open) return;
        setName(initial?.name || "");
        setDescription(initial?.description || "");
        setTagsText((initial?.tags || []).join("\n"));
    }, [open, initial]);

    const handleUploadTxt = (event: ChangeEvent<HTMLInputElement>) => {
        const file = event.target.files?.[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = (readerEvent) => {
            const text = String(readerEvent.target?.result || "");
            const merged = parseTags(text);
            setTagsText(merged.join("\n"));
        };
        reader.readAsText(file);
        event.target.value = "";
    };

    const handleSave = async () => {
        const trimmedName = name.trim();
        if (!trimmedName) {
            toast({ variant: "error", description: t("build.tagLibraryNameRequired", "标签库名称不能为空") });
            return;
        }
        if (tags.length > TAG_LIMIT) {
            toast({ variant: "error", description: t("build.tagLibraryLimit", "单个标签库最多 200 个标签") });
            return;
        }
        setSaving(true);
        const payload = {
            name: trimmedName,
            description: description.trim(),
            tags,
        };
        const req =
            mode === "edit" && initial
                ? updateKnowledgeSpaceTagLibraryApi(initial.id, payload)
                : createKnowledgeSpaceTagLibraryApi({ ...payload });
        const res = await captureAndAlertRequestErrorHoc(req);
        setSaving(false);
        if (!res) return;
        toast({ variant: "success", description: t("build.saved", "已保存") });
        onOpenChange(false);
        onSaved();
    };

    const title =
        mode === "edit"
            ? t("build.renameTag", "重命名标签")
            : t("build.addTag", "新增标签");

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="sm:max-w-[680px] bg-background-login">
                <DialogHeader>
                    <DialogTitle>{title}</DialogTitle>
                </DialogHeader>
                <div className="space-y-5 py-2">
                    <div>
                        <Label className="bisheng-label">
                            {t("build.tagLibraryName", "标签库名称")}<span className="bisheng-tip">*</span>
                        </Label>
                        <Input
                            className="mt-2"
                            value={name}
                            maxLength={200}
                            onChange={(e) => setName(e.target.value)}
                        />
                    </div>
                    <div>
                        <Label className="bisheng-label">{t("build.description", "说明")}</Label>
                        <Textarea
                            className="mt-2 min-h-20"
                            value={description}
                            maxLength={1000}
                            onChange={(e) => setDescription(e.target.value)}
                        />
                    </div>
                    <div>
                        <div className="mb-2 flex items-center justify-between">
                            <Label className="bisheng-label">{t("build.tags", "标签")}</Label>
                            <span className="text-xs text-muted-foreground">{tags.length}/{TAG_LIMIT}</span>
                        </div>
                        <div className="relative">
                            <Textarea
                                className="min-h-64 resize-none pr-24 font-mono text-sm"
                                value={tagsText}
                                onChange={(e) => setTagsText(e.target.value)}
                                placeholder={t("build.tagLibraryTagsPlaceholder", "每行一个标签")}
                            />
                            <input
                                type="file"
                                accept=".txt"
                                id={fileInputId}
                                className="hidden"
                                onChange={handleUploadTxt}
                            />
                            <Label
                                htmlFor={fileInputId}
                                className="absolute right-2 top-2 flex cursor-pointer items-center gap-1"
                            >
                                <Upload color="blue" className="size-3" />
                                <span className="text-xs text-primary">
                                    {t("build.txtFile", "txt文件")}
                                </span>
                            </Label>
                        </div>
                    </div>
                </div>
                <DialogFooter>
                    <Button variant="outline" className="px-8" onClick={() => onOpenChange(false)}>
                        {t("cancel", { ns: "bs" })}
                    </Button>
                    <Button className="px-8" disabled={saving} onClick={handleSave}>
                        {t("confirm", { ns: "bs" })}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}


function TagDialog({ open, mode, initial, onOpenChange, onSaved }: TagDialogProps) {
    const { t } = useTranslation();
    const { toast } = useToast();
    const fileInputId = useRef(`tag-library-txt-${Math.random().toString(36).slice(2)}`).current;
    const [name, setName] = useState("");
    const [originName, setOriginName] = useState("");
    const [resourceType, setResourceType] = useState("");
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        if (!open) return;
        setName("");
        setOriginName(initial?.tag_name || "");
        setResourceType(initial?.resource_type || "");
    }, [open, initial]);

    const handleSave = async () => {
        const trimmedName = name.trim();
        if (!trimmedName) {
            toast({ variant: "error", description: t("build.tagNameRequired", "标签名称不能为空") });
            return;
        }
        setSaving(true);
        const payload = {
            tag_name: trimmedName,
            resource_type: resourceType,
        };
        const req =
            mode === "edit" && initial
                ? updateKnowledgeSpaceTagApi({ original_tag_name: originName, ...payload })
                : createKnowledgeSpaceTagApi({ ...payload });
        const res = await captureAndAlertRequestErrorHoc(req);
        setSaving(false);
        if (!res) return;
        toast({ variant: "success", description: t("build.saved", "已保存") });
        onOpenChange(false);
        onSaved();
    };

    const title =
        mode === "edit"
            ? t("build.renameTag", "重命名标签")
            : t("build.addTag", "新增标签");

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="sm:max-w-[400px] bg-background-login">
                <DialogHeader>
                    <DialogTitle>{title}</DialogTitle>
                </DialogHeader>
                 <p className="mt-1 text-sm text-[#86909C]">
                    {t(
                        "build.autoTagGenerationDesc",
                        "加入平台词表后，AI打标与人工选标均可使用。",
                    )}
                </p>
                {mode === "edit" && (
                    <div className="space-y-5 py-2">
                        <div>
                            <Label className="bisheng-label">
                            {t("build.originalTagName", "原标签名")}: {originName}
                            </Label>
                        </div>
                    </div>
                )}
                <div className="space-y-5 py-2">
                    <div>
                        <Label className="bisheng-label">
                            {t("build.tagNewName", "新标签名")}<span className="bisheng-tip">*</span>
                        </Label>
                        <Input 
                            placeholder={t("build.tagNamePlaceholder", "例如：安全生产")}
                            className="mt-2"
                            value={name}
                            maxLength={100}
                            onChange={(e) => setName(e.target.value)}
                        />
                    </div>
                </div>
                <DialogFooter>
                    <Button variant="outline" className="px-8" onClick={() => onOpenChange(false)}>
                        {t("cancel", { ns: "bs" })}
                    </Button>
                    <Button className="px-8" disabled={saving} onClick={handleSave}>
                        {t("confirm", { ns: "bs" })}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}


const PAGE_SIZE = 10;

export default function KnowledgeSpaceTagSection({
    visible,
    onToggle,
}: KnowledgeSpaceTagSectionProps) {
    const { t } = useTranslation();
    const { toast } = useToast();
    const [keyword, setKeyword] = useState("");
    const [rows, setRows] = useState<KnowledgeSpaceTagListItem[]>([]);
    const [loading, setLoading] = useState(false);
    const [page, setPage] = useState(1);
    const [total, setTotal] = useState(0);
    const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
    const [dialogOpen, setDialogOpen] = useState(false);
    const [dialogMode, setDialogMode] = useState<"create" | "edit">("create");
    const [editing, setEditing] = useState<KnowledgeSpaceTagDetail | null>(null);

    const loadData = useCallback(async (targetPage: number) => {
        setLoading(true);
        const res = await captureAndAlertRequestErrorHoc(
            getKnowledgeSpaceTagListApi({ page: targetPage, page_size: PAGE_SIZE, keyword: keyword }),
        );
        if (res) {
            setRows(res.data || []);
            setTotal(res.total || 0);
        }
        setLoading(false);
    }, [keyword]);

    useEffect(() => {
        if (visible) {
            setPage(1);
            loadData(1);
        }
    }, [visible, keyword]);

    const handlePageChange = (newPage: number) => {
        setPage(newPage);
        loadData(newPage);
    };

    const filteredRows = useMemo(() => {
        return rows;
    }, [rows]);

    const openCreate = () => {
        setDialogMode("create");
        setEditing(null);
        setDialogOpen(true);
    };

    const openEdit = async (row: KnowledgeSpaceTagListItem) => {
        setDialogMode("edit");
        setEditing(row);
        setDialogOpen(true);
    };

    const handleDelete = async (row: KnowledgeSpaceTagListItem) => {
        // Look up the blast radius before showing the confirm dialog so the admin
        // sees exactly how many knowledge spaces will have their auto-tag binding
        // cleared. Falls back to a generic warning if the lookup fails.
        const count = row?.resource_count ?? 0;
        const desc = count > 0
            ? t(
                "build.deleteTagDescWithCount",
                "删除后将影响 {{count}} 个知识文件，这些文件的自动生成标签会被关闭。不能继续操作。",
                { count },
            )
            : t(
                "build.deleteTagDescEmpty",
                "当前没有知识文件绑定此标签。是否继续删除？",
            );
        bsConfirm({
            title: t("build.deleteTagTitle", "删除标签"),
            desc,
            showClose: true,
            okTxt: t("build.confirmDelete", "确认删除"),
            canelTxt: t("cancel", { ns: "bs" }),
            okHidden: count > 0,
            async onOk(next) {
                const res = await captureAndAlertRequestErrorHoc(
                    deleteKnowledgeSpaceTagApi({ tag_name: row.tag_name, resource_type: row.resource_type }),
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
                            {t("build.autoTagGenerationTitle", "标签管理")}
                        </p>
                        <p className="mt-1 text-sm text-[#86909C]">
                            {t(
                                "build.autoTagGenerationDesc",
                                "维护平台统一标签词表；AI打标优先从此选取，词表外推荐进入审核。",
                            )}
                        </p>
                    </div>
                    <Switch checked={visible} onCheckedChange={onToggle} />
                </div>

                {visible && (
                    <div className="mt-4 rounded-lg border border-[#ECECEC] bg-[#FAFBFC] p-4">
                        <div className="mb-3 flex items-center gap-2">
                            <SearchInput
                                className="w-[280px]"
                                placeholder={t("build.searchTag", "按标签名搜索")}
                                value={keyword}
                                onChange={(e) => setKeyword(e.target.value)}
                            />
                            <div className="ml-auto">
                                <Button onClick={openCreate}>
                                    <Plus className="mr-2 size-4" />
                                    {t("build.addTag", "新增标签")}
                                </Button>
                            </div>
                        </div>

                        <div className="max-h-[180px] overflow-y-auto rounded-md border bg-background">
                            <table className="w-full table-fixed border-collapse">
                                <thead className="sticky top-0 z-10 bg-background">
                                    <tr className="text-left text-sm text-muted-foreground">
                                        <th className="w-[28%] px-4 py-3 font-medium">
                                            {t("build.tagName", "标签名称")}
                                        </th>
                                        <th className="w-[28%] px-4 py-3 font-medium">
                                            {t("build.tagSource", "标签来源")}
                                        </th>
                                        <th className="w-[200px] px-4 py-3 font-medium">
                                            {t("build.tagUsedCount", "使用知识数")}
                                        </th>
                                        <th className="w-[320px] px-4 py-3 font-medium">
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
                                                {t("build.tagEmpty", "暂无平台标签，请在右侧增加")}
                                            </td>
                                        </tr>
                                    ) : (
                                        filteredRows.map((row) => (
                                            <tr key={row.tag_name} className="border-t text-sm">
                                                <td className="truncate px-4 py-3 font-medium">{row.tag_name}</td>
                                                <td className="truncate px-4 py-3 font-medium">{row.resource_type === "system_tag" ? "系统标签" : (row.resource_type === "ai_auto_tag" ? "AI标签" : "人工标签")}</td>
                                                <td className="px-4 py-3">{row.resource_count}</td>
                                                <td className="px-4 py-3">
                                                    <div className="flex items-center gap-1">
                                                        <Button variant="ghost" size="icon" onClick={() => openEdit(row)}>
                                                            <Pencil className="size-4" />
                                                        </Button>
                                                        <Button
                                                            variant="ghost"
                                                            size="icon"
                                                            onClick={() => handleDelete(row)}
                                                        >
                                                            <Trash2 className="size-4" />
                                                        </Button>
                                                    </div>
                                                </td>
                                            </tr>
                                        ))
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

            <TagDialog
                open={dialogOpen}
                mode={dialogMode}
                initial={editing}
                onOpenChange={setDialogOpen}
                onSaved={() => loadData(page)}
            />
        </div>
    );
}
