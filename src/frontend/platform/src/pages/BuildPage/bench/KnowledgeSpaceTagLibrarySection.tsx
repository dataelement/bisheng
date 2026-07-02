import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { Input, SearchInput, Textarea } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { Switch } from "@/components/bs-ui/switch";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger, Portal } from "@/components/bs-ui/tooltip";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import {
    createKnowledgeSpaceTagLibraryApi,
    deleteKnowledgeSpaceTagLibraryApi,
    getKnowledgeSpaceTagLibrariesApi,
    getKnowledgeSpaceTagLibraryApi,
    getKnowledgeSpaceTagLibraryUsageApi,
    updateKnowledgeSpaceTagLibraryApi,
    type KnowledgeSpaceTagLibraryDetail,
    type KnowledgeSpaceTagLibraryListItem,
    type KnowledgeSpaceTagLibraryTagItem,
} from "@/controllers/API/knowledgeSpaceTagLibrary";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { Pencil, Plus, Trash2 } from "lucide-react";
import type { MouseEvent } from "react";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

const PAGE_SIZE = 10;
const TAG_LIMIT = 200;
const TAG_LIBRARY_NAME_MAX_LENGTH = 20;
const BOUND_SPACE_NAME_MAX_CHARS = 12;

function BoundSpaceNamesCell({ names }: { names: string[] }) {
    if (!names.length) {
        return <span className="text-muted-foreground">-</span>;
    }
    const fullText = names.join("、");
    const truncated =
        fullText.length > BOUND_SPACE_NAME_MAX_CHARS
            ? `${fullText.slice(0, BOUND_SPACE_NAME_MAX_CHARS)}...`
            : fullText;

    if (truncated === fullText) {
        return <span className="block truncate">{fullText}</span>;
    }

    return (
        <TooltipProvider delayDuration={100}>
            <Tooltip>
                <TooltipTrigger asChild>
                    <span className="block cursor-default truncate">{truncated}</span>
                </TooltipTrigger>
                <Portal>
                    <TooltipContent side="top" className="max-w-96">
                        <div className="whitespace-normal break-all text-left">{fullText}</div>
                    </TooltipContent>
                </Portal>
            </Tooltip>
        </TooltipProvider>
    );
}

function formatTagSource(resourceType: string, t: (key: string, defaultValue: string) => string) {
    if (resourceType === "ai_auto_tag") {
        return t("build.tagSourceAi", "AI标签");
    }
    if (resourceType === "system_tag" || resourceType === "manual_tag") {
        return t("build.tagSourceSystem", "系统标签");
    }
    return t("build.tagSourceManual", "人工标签");
}

function formatDateTime(value?: string | null) {
    if (!value) return "-";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "-";
    const pad = (num: number) => String(num).padStart(2, "0");
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function splitTagItems(items: KnowledgeSpaceTagLibraryTagItem[]) {
    const manualTags = items
        .filter((item) => item.resource_type === "manual_tag" || item.resource_type === "system_tag")
        .map((item) => item.name);
    const aiTags = items.filter((item) => item.resource_type === "ai_auto_tag").map((item) => item.name);
    return { manualTags, aiTags };
}

interface KnowledgeSpaceTagLibrarySectionProps {
    visible: boolean;
    onToggle: (visible: boolean) => void;
}

interface TagLibraryFormDialogProps {
    open: boolean;
    mode: "create" | "edit";
    initial?: KnowledgeSpaceTagLibraryDetail | null;
    onOpenChange: (open: boolean) => void;
    onSaved: () => void;
}

interface LibraryTagsDialogProps {
    open: boolean;
    library: KnowledgeSpaceTagLibraryListItem | null;
    onOpenChange: (open: boolean) => void;
    onUpdated: () => void;
}

function TagLibraryFormDialog({ open, mode, initial, onOpenChange, onSaved }: TagLibraryFormDialogProps) {
    const { t } = useTranslation();
    const { toast } = useToast();
    const [name, setName] = useState("");
    const [description, setDescription] = useState("");
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        if (!open) return;
        setName(initial?.name || "");
        setDescription(initial?.description || "");
    }, [open, initial]);

    const handleSave = async () => {
        const trimmedName = name.trim();
        if (!trimmedName) {
            toast({ variant: "error", description: t("build.tagLibraryNameRequired", "标签库名称不能为空") });
            return;
        }
        if (trimmedName.length > TAG_LIBRARY_NAME_MAX_LENGTH) {
            toast({
                variant: "error",
                description: t("build.tagLibraryNameMaxLength", "标签库名称不能超过20个字符"),
            });
            return;
        }
        setSaving(true);
        const payload = {
            name: trimmedName,
            description: description.trim(),
        };
        const req =
            mode === "edit" && initial
                ? updateKnowledgeSpaceTagLibraryApi(initial.id, payload)
                : createKnowledgeSpaceTagLibraryApi({ ...payload, tags: [] });
        const res = await captureAndAlertRequestErrorHoc(req);
        setSaving(false);
        if (!res) return;
        toast({ variant: "success", description: t("build.saved", "已保存") });
        onOpenChange(false);
        onSaved();
    };

    const title =
        mode === "edit"
            ? t("build.editTagLibrary", "编辑标签库")
            : t("build.createTagLibrary", "新增标签库");

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="sm:max-w-[520px] bg-background-login">
                <DialogHeader>
                    <DialogTitle>{title}</DialogTitle>
                </DialogHeader>
                <form
                    autoComplete="off"
                    className="space-y-5 py-2"
                    onSubmit={(event) => {
                        event.preventDefault();
                        void handleSave();
                    }}
                >
                    <div>
                        <Label className="bisheng-label" htmlFor="tag-library-name">
                            {t("build.tagLibraryName", "标签库名称")}<span className="bisheng-tip">*</span>
                        </Label>
                        <Input
                            id="tag-library-name"
                            name="tag-library-name"
                            type="text"
                            autoComplete="off"
                            autoCorrect="off"
                            autoCapitalize="off"
                            spellCheck={false}
                            data-1p-ignore
                            data-lpignore="true"
                            data-form-type="other"
                            className="mt-2"
                            value={name}
                            maxLength={TAG_LIBRARY_NAME_MAX_LENGTH}
                            placeholder={t("build.tagLibraryNamePlaceholder", "请输入标签库名称")}
                            onChange={(e) => setName(e.target.value)}
                        />
                    </div>
                    <div>
                        <Label className="bisheng-label" htmlFor="tag-library-description">
                            {t("build.description", "说明")}
                        </Label>
                        <Textarea
                            id="tag-library-description"
                            name="tag-library-description"
                            autoComplete="off"
                            autoCorrect="off"
                            autoCapitalize="off"
                            spellCheck={false}
                            data-1p-ignore
                            data-lpignore="true"
                            data-form-type="other"
                            className="mt-2 min-h-20"
                            value={description}
                            maxLength={1000}
                            onChange={(e) => setDescription(e.target.value)}
                        />
                    </div>
                    <DialogFooter>
                        <Button type="button" variant="outline" className="px-8" onClick={() => onOpenChange(false)}>
                            {t("cancel", { ns: "bs" })}
                        </Button>
                        <Button type="submit" className="px-8" disabled={saving}>
                            {t("confirm", { ns: "bs" })}
                        </Button>
                    </DialogFooter>
                </form>
            </DialogContent>
        </Dialog>
    );
}

function LibraryTagsDialog({ open, library, onOpenChange, onUpdated }: LibraryTagsDialogProps) {
    const { t } = useTranslation();
    const { toast } = useToast();
    const [tagItems, setTagItems] = useState<KnowledgeSpaceTagLibraryTagItem[]>([]);
    const [newTag, setNewTag] = useState("");
    const [loading, setLoading] = useState(false);
    const [saving, setSaving] = useState(false);

    const loadTags = useCallback(async () => {
        if (!library?.id) return;
        setLoading(true);
        const res = await captureAndAlertRequestErrorHoc(getKnowledgeSpaceTagLibraryApi(library.id));
        if (res) {
            if (res.tag_items?.length) {
                setTagItems(res.tag_items);
            } else {
                setTagItems(
                    (res.tags || []).map((name) => ({
                        name,
                        resource_type: "manual_tag",
                    })),
                );
            }
        }
        setLoading(false);
    }, [library?.id]);

    useEffect(() => {
        if (!open || !library?.id) return;
        setNewTag("");
        loadTags();
    }, [open, library?.id, loadTags]);

    const persistTagItems = async (nextItems: KnowledgeSpaceTagLibraryTagItem[]) => {
        if (!library?.id) return false;
        if (nextItems.length > TAG_LIMIT) {
            toast({ variant: "error", description: t("build.tagLibraryLimit", "单个标签库最多 200 个标签") });
            return false;
        }
        const { manualTags, aiTags } = splitTagItems(nextItems);
        setSaving(true);
        const res = await captureAndAlertRequestErrorHoc(
            updateKnowledgeSpaceTagLibraryApi(library.id, { tags: manualTags, ai_tags: aiTags }),
        );
        setSaving(false);
        if (!res) return false;
        setTagItems(
            res.tag_items?.length
                ? res.tag_items
                : (res.tags || []).map((name) => ({ name, resource_type: "manual_tag" })),
        );
        onUpdated();
        return true;
    };

    const handleAddTag = async () => {
        const trimmed = newTag.trim();
        if (!trimmed) {
            toast({ variant: "error", description: t("build.tagNameRequired", "标签名称不能为空") });
            return;
        }
        if (tagItems.some((item) => item.name === trimmed)) {
            toast({ variant: "error", description: t("build.tagAlreadyExists", "标签已存在") });
            return;
        }
        const ok = await persistTagItems([
            ...tagItems,
            { name: trimmed, resource_type: "manual_tag" },
        ]);
        if (ok) {
            setNewTag("");
            toast({ variant: "success", description: t("build.saved", "已保存") });
        }
    };

    const handleDeleteTag = (item: KnowledgeSpaceTagLibraryTagItem) => {
        bsConfirm({
            title: t("build.deleteTagTitle", "删除标签"),
            desc: t("build.deleteTagFromLibraryDesc", "确定从该标签库中删除此标签？"),
            showClose: true,
            okTxt: t("build.confirmDelete", "确认删除"),
            canelTxt: t("cancel", { ns: "bs" }),
            async onOk(next) {
                const ok = await persistTagItems(
                    tagItems.filter(
                        (tag) => !(tag.name === item.name && tag.resource_type === item.resource_type),
                    ),
                );
                if (ok) {
                    toast({ variant: "success", description: t("build.deleted", "已删除") });
                }
                next?.();
            },
        });
    };

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="sm:max-w-[920px] bg-background-login">
                <DialogHeader>
                    <DialogTitle>
                        {t("build.tagLibraryTagsTitle", "标签库标签")} — {library?.name || ""}
                    </DialogTitle>
                </DialogHeader>
                <div className="space-y-4 py-2">
                    <div className="flex items-center gap-2">
                        <Input
                            id="tag-library-tag-name"
                            name="tag-library-tag-name"
                            type="text"
                            autoComplete="off"
                            autoCorrect="off"
                            autoCapitalize="off"
                            spellCheck={false}
                            data-1p-ignore
                            data-lpignore="true"
                            data-form-type="other"
                            className="flex-1"
                            value={newTag}
                            maxLength={100}
                            placeholder={t("build.tagNamePlaceholder", "例如：安全生产")}
                            onChange={(e) => setNewTag(e.target.value)}
                            onKeyDown={(e) => {
                                if (e.key === "Enter") {
                                    e.preventDefault();
                                    handleAddTag();
                                }
                            }}
                        />
                        <Button disabled={saving} onClick={handleAddTag}>
                            <Plus className="mr-1 size-4" />
                            {t("build.addTag", "新增标签")}
                        </Button>
                    </div>
                    <div className="max-h-64 overflow-y-auto rounded-md border bg-background">
                        <table className="w-full table-fixed border-collapse">
                            <thead className="sticky top-0 z-10 bg-background">
                                <tr className="text-left text-sm text-muted-foreground">
                                    <th className="w-[22%] px-3 py-3 font-medium">{t("build.tagName", "标签名称")}</th>
                                    <th className="w-[14%] px-3 py-3 font-medium">{t("build.tagSource", "标签来源")}</th>
                                    <th className="w-[12%] px-3 py-3 font-medium">{t("build.tagUsedCount", "使用知识数")}</th>
                                    <th className="w-[18%] px-3 py-3 font-medium">{t("build.createTime", "创建时间")}</th>
                                    <th className="w-[14%] px-3 py-3 font-medium">{t("build.creator", "创建者")}</th>
                                    <th className="w-[10%] px-3 py-3 font-medium">{t("build.operation", "操作")}</th>
                                </tr>
                            </thead>
                            <tbody>
                                {loading ? (
                                    <tr>
                                        <td className="px-3 py-8 text-center text-sm text-muted-foreground" colSpan={6}>
                                            {t("loading")}
                                        </td>
                                    </tr>
                                ) : tagItems.length === 0 ? (
                                    <tr>
                                        <td className="px-3 py-8 text-center text-sm text-muted-foreground" colSpan={6}>
                                            {t("build.tagLibraryTagsEmpty", "暂无标签，请在上方添加")}
                                        </td>
                                    </tr>
                                ) : (
                                    tagItems.map((item) => (
                                        <tr
                                            key={`${item.resource_type}-${item.name}`}
                                            className="border-t text-sm"
                                        >
                                            <td className="truncate px-3 py-3 font-medium">{item.name}</td>
                                            <td className="truncate px-3 py-3 text-muted-foreground">
                                                {formatTagSource(item.resource_type, t)}
                                            </td>
                                            <td className="px-3 py-3">{item.resource_count ?? 0}</td>
                                            <td className="truncate px-3 py-3 text-muted-foreground">
                                                {formatDateTime(item.create_time)}
                                            </td>
                                            <td className="truncate px-3 py-3 text-muted-foreground">
                                                {item.creator_name || "-"}
                                            </td>
                                            <td className="px-3 py-3">
                                                <Button
                                                    variant="ghost"
                                                    size="icon"
                                                    disabled={saving}
                                                    onClick={() => handleDeleteTag(item)}
                                                >
                                                    <Trash2 className="size-4" />
                                                </Button>
                                            </td>
                                        </tr>
                                    ))
                                )}
                            </tbody>
                        </table>
                    </div>
                    <p className="text-xs text-muted-foreground">
                        {tagItems.length}/{TAG_LIMIT}
                    </p>
                </div>
                <DialogFooter>
                    <Button variant="outline" className="px-8" onClick={() => onOpenChange(false)}>
                        {t("close", { ns: "bs", defaultValue: "关闭" })}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}

export default function KnowledgeSpaceTagLibrarySection({
    visible,
    onToggle,
}: KnowledgeSpaceTagLibrarySectionProps) {
    const { t } = useTranslation();
    const { toast } = useToast();
    const [keyword, setKeyword] = useState("");
    const [rows, setRows] = useState<KnowledgeSpaceTagLibraryListItem[]>([]);
    const [loading, setLoading] = useState(false);
    const [page, setPage] = useState(1);
    const [total, setTotal] = useState(0);
    const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
    const [formDialogOpen, setFormDialogOpen] = useState(false);
    const [formDialogMode, setFormDialogMode] = useState<"create" | "edit">("create");
    const [editingLibrary, setEditingLibrary] = useState<KnowledgeSpaceTagLibraryDetail | null>(null);
    const [tagsDialogOpen, setTagsDialogOpen] = useState(false);
    const [selectedLibrary, setSelectedLibrary] = useState<KnowledgeSpaceTagLibraryListItem | null>(null);

    const loadData = useCallback(async (targetPage: number) => {
        setLoading(true);
        const res = await captureAndAlertRequestErrorHoc(
            getKnowledgeSpaceTagLibrariesApi({ page: targetPage, page_size: PAGE_SIZE, keyword: keyword || undefined }),
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

    const openCreate = () => {
        setFormDialogMode("create");
        setEditingLibrary(null);
        setFormDialogOpen(true);
    };

    const openEdit = async (row: KnowledgeSpaceTagLibraryListItem, event: MouseEvent) => {
        event.stopPropagation();
        const detail = await captureAndAlertRequestErrorHoc(getKnowledgeSpaceTagLibraryApi(row.id));
        if (!detail) return;
        setFormDialogMode("edit");
        setEditingLibrary(detail);
        setFormDialogOpen(true);
    };

    const openTagsDialog = (row: KnowledgeSpaceTagLibraryListItem) => {
        setSelectedLibrary(row);
        setTagsDialogOpen(true);
    };

    const handleDelete = async (row: KnowledgeSpaceTagLibraryListItem, event: MouseEvent) => {
        event.stopPropagation();
        if (row.tag_count > 0) {
            toast({
                variant: "error",
                description: t("build.deleteTagLibraryHasTags", "标签库中存在标签，无法删除"),
            });
            return;
        }
        const usage = await captureAndAlertRequestErrorHoc(getKnowledgeSpaceTagLibraryUsageApi(row.id));
        const count = usage?.count ?? 0;
        if (count > 0) {
            toast({
                variant: "error",
                description: t("build.deleteTagLibraryHasBindings", "标签库已关联知识空间，无法删除"),
            });
            return;
        }
        bsConfirm({
            title: t("build.deleteTagLibraryTitle", "删除标签库"),
            desc: t("build.deleteTagLibraryConfirm", "确定删除该空标签库吗？"),
            showClose: true,
            okTxt: t("build.confirmDelete", "确认删除"),
            canelTxt: t("cancel", { ns: "bs" }),
            async onOk(next) {
                const res = await captureAndAlertRequestErrorHoc(deleteKnowledgeSpaceTagLibraryApi(row.id));
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
                            {t("build.tagLibraryManagementTitle", "标签库管理")}
                        </p>
                        <p className="mt-1 text-sm text-[#86909C]">
                            {t(
                                "build.tagLibraryManagementDesc",
                                "维护平台标签库；知识空间可绑定一个或多个标签库，AI 打标从库中选取候选标签。",
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
                                placeholder={t("build.searchTagLibrary", "按标签库名搜索")}
                                value={keyword}
                                onChange={(e) => setKeyword(e.target.value)}
                            />
                            <div className="ml-auto">
                                <Button onClick={openCreate}>
                                    <Plus className="mr-2 size-4" />
                                    {t("build.createTagLibrary", "新增标签库")}
                                </Button>
                            </div>
                        </div>

                        <div className="max-h-[220px] overflow-y-auto overflow-x-auto rounded-md border bg-background">
                            <table className="w-full min-w-[760px] table-fixed border-collapse">
                                <thead className="sticky top-0 z-10 bg-background">
                                    <tr className="text-left text-sm text-muted-foreground">
                                        <th className="w-[22%] px-4 py-3 font-medium">
                                            {t("build.tagLibraryName", "标签库名称")}
                                        </th>
                                        <th className="w-[10%] px-4 py-3 font-medium">
                                            {t("build.tagCount", "标签数量")}
                                        </th>
                                        <th className="w-[12%] px-4 py-3 font-medium">
                                            {t("build.boundKnowledgeSpaces", "关联知识库")}
                                        </th>
                                        <th className="w-[12%] px-4 py-3 font-medium">
                                            {t("build.totalKnowledgeUsage", "使用知识总数")}
                                        </th>
                                        <th className="w-[12%] px-4 py-3 font-medium">
                                            {t("build.viewTags", "查看标签")}
                                        </th>
                                        <th className="w-[32%] px-4 py-3 font-medium">
                                            {t("build.operation", "操作")}
                                        </th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {loading ? (
                                        <tr>
                                            <td className="px-4 py-10 text-center text-sm text-muted-foreground" colSpan={6}>
                                                {t("loading")}
                                            </td>
                                        </tr>
                                    ) : rows.length === 0 ? (
                                        <tr>
                                            <td className="px-4 py-10 text-center text-sm text-muted-foreground" colSpan={6}>
                                                {t("build.tagLibraryEmpty", "暂无标签库，请点击右上角新增")}
                                            </td>
                                        </tr>
                                    ) : (
                                        rows.map((row) => (
                                            <tr
                                                key={row.id}
                                                className="border-t text-sm hover:bg-muted/40"
                                            >
                                                <td className="truncate px-4 py-3 font-medium">{row.name}</td>
                                                <td className="px-4 py-3">{row.tag_count}</td>
                                                <td className="px-4 py-3">
                                                    <BoundSpaceNamesCell names={row.bound_space_names || []} />
                                                </td>
                                                <td className="px-4 py-3">{row.used_knowledge_count ?? 0}</td>
                                                <td className="px-4 py-3">
                                                    <Button
                                                        variant="link"
                                                        className="h-auto p-0"
                                                        onClick={() => openTagsDialog(row)}
                                                    >
                                                        {t("build.viewTags", "查看标签")}
                                                    </Button>
                                                </td>
                                                <td className="px-4 py-3">
                                                    <div className="flex items-center gap-1">
                                                        <Button variant="ghost" size="icon" onClick={(e) => openEdit(row, e)}>
                                                            <Pencil className="size-4" />
                                                        </Button>
                                                        <Button
                                                            variant="ghost"
                                                            size="icon"
                                                            disabled={row.tag_count > 0}
                                                            onClick={(e) => handleDelete(row, e)}
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
                )}
            </div>

            <TagLibraryFormDialog
                open={formDialogOpen}
                mode={formDialogMode}
                initial={editingLibrary}
                onOpenChange={setFormDialogOpen}
                onSaved={() => loadData(page)}
            />

            <LibraryTagsDialog
                open={tagsDialogOpen}
                library={selectedLibrary}
                onOpenChange={setTagsDialogOpen}
                onUpdated={() => loadData(page)}
            />
        </div>
    );
}
