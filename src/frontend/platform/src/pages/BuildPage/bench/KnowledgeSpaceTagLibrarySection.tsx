import { Button, Input, SearchInput, Textarea, notification } from '@bisheng/ui';
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";

import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";

import { Label } from "@/components/bs-ui/label";

import {
    createKnowledgeSpaceTagLibraryApi,
    deleteKnowledgeSpaceTagLibraryApi,
    getKnowledgeSpaceTagLibrariesApi,
    getKnowledgeSpaceTagLibraryApi,
    getKnowledgeSpaceTagLibraryUsageApi,
    updateKnowledgeSpaceTagLibraryApi,
    type KnowledgeSpaceTagLibraryDetail,
    type KnowledgeSpaceTagLibraryListItem,
} from "@/controllers/API/knowledgeSpaceTagLibrary";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { Switch } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";

import type { ChangeEvent } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

const LIST_PAGE_SIZE = 200;
const TAG_LIMIT = 200;

interface KnowledgeSpaceTagLibrarySectionProps {
    visible: boolean;
    onToggle: (visible: boolean) => void;
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
        if ((String((name) ?? '').length > 200) || (String((description) ?? '').length > 1000)) return;

        const trimmedName = name.trim();
        if (!trimmedName) {
            notification.open({ type: "error", description: String(t("build.tagLibraryNameRequired") ?? '') });
            return;
        }
        if (tags.length > TAG_LIMIT) {
            notification.open({ type: "error", description: String(t("build.tagLibraryLimit") ?? '') });
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
        notification.open({ type: "success", description: String(t("build.saved") ?? '') });
        onOpenChange(false);
        onSaved();
    };

    const title = mode === "edit" ? t("build.editTagLibrary") : t("build.createTagLibrary");

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="sm:max-w-[680px] bg-background-login">
                <DialogHeader>
                    <DialogTitle>{title}</DialogTitle>
                </DialogHeader>
                <div className="space-y-5 py-2">
                    <div>
                        <Label className="bisheng-label">
                            {t("build.tagLibraryName")}
                            <span className="bisheng-tip">*</span>
                        </Label>
                        <Input value={name} maxLength={200} onChange={(e) => setName(e.target.value)} className={"mt-2"} showCount />
                    </div>
                    <div>
                        <Label className="bisheng-label">{t("build.description")}</Label>
                        <Textarea value={description} maxLength={1000} onChange={(e) => setDescription(e.target.value)} textareaClassName={"mt-2 min-h-20"} showCount />
                    </div>
                    <div>
                        <div className="mb-2 flex items-center justify-between">
                            <Label className="bisheng-label">{t("build.tags")}</Label>
                            <span className="text-xs text-muted-foreground">
                                {tags.length}/{TAG_LIMIT}
                            </span>
                        </div>
                        <div className="relative">
                            <Textarea value={tagsText} onChange={(e) => setTagsText(e.target.value)} placeholder={t("build.tagLibraryTagsPlaceholder")} textareaClassName={"min-h-64 resize-none pr-24 font-mono text-sm"} />
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
                                <Outlined.Upload color="blue" className="size-3" />
                                <span className="text-xs text-primary">{t("build.txtFile")}</span>
                            </Label>
                        </div>
                    </div>
                </div>
                <DialogFooter>
                    <Button variant="outlined" onClick={() => onOpenChange(false)} color="default">
                        {t("cancel", { ns: "bs" })}
                    </Button>
                    <Button disabled={((String((name) ?? '').length > 200) || (String((description) ?? '').length > 1000)) || (saving)} onClick={handleSave}>
                        {t("confirm", { ns: "bs" })}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}

export default function KnowledgeSpaceTagLibrarySection({ visible, onToggle }: KnowledgeSpaceTagLibrarySectionProps) {
    const { t } = useTranslation();

    const [keyword, setKeyword] = useState("");
    const [rows, setRows] = useState<KnowledgeSpaceTagLibraryListItem[]>([]);
    const [loading, setLoading] = useState(false);
    const [dialogOpen, setDialogOpen] = useState(false);
    const [dialogMode, setDialogMode] = useState<"create" | "edit">("create");
    const [editing, setEditing] = useState<KnowledgeSpaceTagLibraryDetail | null>(null);

    const loadData = useCallback(async () => {
        setLoading(true);
        const res = await captureAndAlertRequestErrorHoc(
            getKnowledgeSpaceTagLibrariesApi({ page: 1, page_size: LIST_PAGE_SIZE }),
        );
        if (res) setRows(res.data || []);
        setLoading(false);
    }, []);

    useEffect(() => {
        if (visible) loadData();
    }, [visible, loadData]);

    const filteredRows = useMemo(() => {
        const trimmed = keyword.trim().toLowerCase();
        if (!trimmed) return rows;
        return rows.filter((row) => row.name.toLowerCase().includes(trimmed));
    }, [rows, keyword]);

    const openCreate = () => {
        setDialogMode("create");
        setEditing(null);
        setDialogOpen(true);
    };

    const openEdit = async (row: KnowledgeSpaceTagLibraryListItem) => {
        const detail = await captureAndAlertRequestErrorHoc(getKnowledgeSpaceTagLibraryApi(row.id));
        if (!detail) return;
        setDialogMode("edit");
        setEditing(detail);
        setDialogOpen(true);
    };

    const handleDelete = async (row: KnowledgeSpaceTagLibraryListItem) => {
        // Look up the blast radius before showing the confirm dialog so the admin
        // sees exactly how many knowledge spaces will have their auto-tag binding
        // cleared. Falls back to a generic warning if the lookup fails.
        const usage = await captureAndAlertRequestErrorHoc(getKnowledgeSpaceTagLibraryUsageApi(row.id));
        const count = usage?.count ?? 0;
        const desc =
            count > 0 ? t("build.deleteTagLibraryDescWithCount", { count }) : t("build.deleteTagLibraryDescEmpty");
        bsConfirm({
            title: t("build.deleteTagLibraryTitle"),
            desc,
            showClose: true,
            okTxt: t("build.confirmDelete"),
            canelTxt: t("cancel", { ns: "bs" }),
            async onOk(next) {
                const res = await captureAndAlertRequestErrorHoc(deleteKnowledgeSpaceTagLibraryApi(row.id));
                if (res) {
                    notification.open({ type: "success", description: String(t("build.deleted") ?? '') });
                    loadData();
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
                        <p className="text-lg font-bold">{t("build.autoTagGenerationTitle")}</p>
                        <p className="mt-1 text-sm text-[#86909C]">{t("build.autoTagGenerationDesc")}</p>
                    </div>
                    <Switch checked={visible} onCheckedChange={onToggle} />
                </div>

                {visible && (
                    <div className="mt-4 rounded-lg border border-[#ECECEC] bg-[#FAFBFC] p-4">
                        <div className="mb-3 flex items-center gap-2">
                            <SearchInput placeholder={t("build.searchTagLibrary")} value={keyword} onChange={(e) => setKeyword(e.target.value)} className={"w-[280px]"} />
                            <div className="ml-auto">
                                <Button onClick={openCreate}>
                                    <Outlined.Plus className="mr-2 size-4" />
                                    {t("build.createTagLibrary")}
                                </Button>
                            </div>
                        </div>

                        <div className="overflow-hidden rounded-md border bg-background">
                            <table className="w-full table-fixed border-collapse">
                                <thead className="bg-muted/40">
                                    <tr className="text-left text-sm text-muted-foreground">
                                        <th className="w-[28%] px-4 py-3 font-medium">{t("build.tagLibraryName")}</th>
                                        <th className="px-4 py-3 font-medium">{t("build.description")}</th>
                                        <th className="w-[100px] px-4 py-3 font-medium">{t("build.tagCount")}</th>
                                        <th className="w-[120px] px-4 py-3 font-medium">{t("build.operation")}</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {loading ? (
                                        <tr>
                                            <td
                                                className="px-4 py-10 text-center text-sm text-muted-foreground"
                                                colSpan={4}
                                            >
                                                {t("loading")}
                                            </td>
                                        </tr>
                                    ) : filteredRows.length === 0 ? (
                                        <tr>
                                            <td
                                                className="px-4 py-10 text-center text-sm text-muted-foreground"
                                                colSpan={4}
                                            >
                                                {t("build.tagLibraryEmpty")}
                                            </td>
                                        </tr>
                                    ) : (
                                        filteredRows.map((row) => (
                                            <tr key={row.id} className="border-t text-sm">
                                                <td className="truncate px-4 py-3 font-medium">{row.name}</td>
                                                <td className="truncate px-4 py-3 text-muted-foreground">
                                                    {row.description || "--"}
                                                </td>
                                                <td className="px-4 py-3">{row.tag_count}</td>
                                                <td className="px-4 py-3">
                                                    <div className="flex items-center gap-1">
                                                        <Button variant="text" size="small" iconOnly onClick={() => openEdit(row)} color="default">
                                                            <Outlined.Edit className="size-4" />
                                                        </Button>
                                                        <Button variant="text" size="small" iconOnly onClick={() => handleDelete(row)} color="default">
                                                            <Outlined.Delete className="size-4" />
                                                        </Button>
                                                    </div>
                                                </td>
                                            </tr>
                                        ))
                                    )}
                                </tbody>
                            </table>
                        </div>
                    </div>
                )}
            </div>

            <TagLibraryDialog
                open={dialogOpen}
                mode={dialogMode}
                initial={editing}
                onOpenChange={setDialogOpen}
                onSaved={loadData}
            />
        </div>
    );
}
