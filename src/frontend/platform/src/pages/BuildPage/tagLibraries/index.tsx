import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { Input, Textarea } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import {
  createKnowledgeSpaceTagLibraryApi,
  deleteKnowledgeSpaceTagLibraryApi,
  getKnowledgeSpaceTagLibrariesApi,
  getKnowledgeSpaceTagLibraryApi,
  importKnowledgeSpaceTagLibraryTextApi,
  updateKnowledgeSpaceTagLibraryApi,
  type KnowledgeSpaceTagLibraryDetail,
  type KnowledgeSpaceTagLibraryListItem,
} from "@/controllers/API/knowledgeSpaceTagLibrary";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { Pencil, Plus, RefreshCw, Search, Trash2, Upload } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

const EMPTY_FORM = {
  name: "",
  description: "",
  tagsText: "",
};

function parseTags(text: string) {
  return text
    .split(/\r?\n/)
    .map((tag) => tag.trim())
    .filter(Boolean);
}

function TagLibraryDialog({
  open,
  mode,
  initial,
  onOpenChange,
  onSaved,
}: {
  open: boolean;
  mode: "create" | "edit" | "import";
  initial?: KnowledgeSpaceTagLibraryDetail | null;
  onOpenChange: (open: boolean) => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const { message } = useToast();
  const [form, setForm] = useState(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const tags = useMemo(() => parseTags(form.tagsText), [form.tagsText]);

  useEffect(() => {
    if (!open) return;
    setForm({
      name: initial?.name || "",
      description: initial?.description || "",
      tagsText: (initial?.tags || []).join("\n"),
    });
  }, [initial, open]);

  const title =
    mode === "edit"
      ? t("build.editTagLibrary", "编辑标签库")
      : mode === "import"
        ? t("build.importTagLibrary", "导入标签库")
        : t("build.createTagLibrary", "创建标签库");

  const handleSave = async () => {
    const name = form.name.trim();
    if (!name) {
      message({ variant: "error", description: t("build.tagLibraryNameRequired", "标签库名称不能为空") });
      return;
    }
    if (tags.length > 200) {
      message({ variant: "error", description: t("build.tagLibraryLimit", "单个标签库最多 200 个标签") });
      return;
    }
    setSaving(true);
    const payload = {
      name,
      description: form.description.trim(),
      tags,
    };
    const req =
      mode === "edit" && initial
        ? updateKnowledgeSpaceTagLibraryApi(initial.id, payload)
        : mode === "import"
          ? importKnowledgeSpaceTagLibraryTextApi({
              name,
              description: form.description.trim(),
              content: form.tagsText,
            })
          : createKnowledgeSpaceTagLibraryApi(payload);
    const res = await captureAndAlertRequestErrorHoc(req);
    setSaving(false);
    if (!res) return;
    message({ variant: "success", description: t("build.saved", "已保存") });
    onOpenChange(false);
    onSaved();
  };

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
              value={form.name}
              maxLength={200}
              onChange={(e) => setForm((prev) => ({ ...prev, name: e.target.value }))}
            />
          </div>
          <div>
            <Label className="bisheng-label">{t("build.description", "说明")}</Label>
            <Textarea
              className="mt-2 min-h-20"
              value={form.description}
              maxLength={1000}
              onChange={(e) => setForm((prev) => ({ ...prev, description: e.target.value }))}
            />
          </div>
          <div>
            <div className="mb-2 flex items-center justify-between">
              <Label className="bisheng-label">{t("build.tags", "标签")}</Label>
              <span className="text-xs text-muted-foreground">{tags.length}/200</span>
            </div>
            <Textarea
              className="min-h-64 font-mono text-sm"
              value={form.tagsText}
              onChange={(e) => setForm((prev) => ({ ...prev, tagsText: e.target.value }))}
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

export default function KnowledgeSpaceTagLibraries() {
  const { t } = useTranslation();
  const { message } = useToast();
  const [keyword, setKeyword] = useState("");
  const [rows, setRows] = useState<KnowledgeSpaceTagLibraryListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogMode, setDialogMode] = useState<"create" | "edit" | "import">("create");
  const [editing, setEditing] = useState<KnowledgeSpaceTagLibraryDetail | null>(null);

  const loadData = async () => {
    setLoading(true);
    const res = await captureAndAlertRequestErrorHoc(
      getKnowledgeSpaceTagLibrariesApi({ page: 1, page_size: 100, keyword: keyword.trim() || undefined }),
    );
    if (res) {
      setRows(res.data || []);
      setTotal(res.total || 0);
    }
    setLoading(false);
  };

  useEffect(() => {
    loadData();
  }, []);

  const openCreate = () => {
    setDialogMode("create");
    setEditing(null);
    setDialogOpen(true);
  };

  const openImport = () => {
    setDialogMode("import");
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
    const res = await captureAndAlertRequestErrorHoc(deleteKnowledgeSpaceTagLibraryApi(row.id));
    if (!res) return;
    message({ variant: "success", description: t("build.deleted", "已删除") });
    loadData();
  };

  return (
    <div className="h-full overflow-y-auto border-t bg-background px-8 py-6">
      <div className="mx-auto max-w-[1120px]">
        <div className="mb-5 flex items-center justify-between gap-4">
          <h1 className="text-xl font-semibold">{t("build.tagLibrary", "标签库")}</h1>
          <div className="flex items-center gap-2">
            <Button variant="outline" onClick={openImport}>
              <Upload className="mr-2 size-4" />
              {t("build.import", "导入")}
            </Button>
            <Button onClick={openCreate}>
              <Plus className="mr-2 size-4" />
              {t("build.create", "创建")}
            </Button>
          </div>
        </div>

        <div className="mb-4 flex items-center gap-2">
          <div className="relative w-[320px]">
            <Search className="pointer-events-none absolute left-3 top-2.5 size-4 text-muted-foreground" />
            <Input
              className="pl-9"
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") loadData();
              }}
            />
          </div>
          <Button variant="outline" onClick={loadData}>
            <RefreshCw className="mr-2 size-4" />
            {t("build.refresh", "刷新")}
          </Button>
          <span className="text-sm text-muted-foreground">{total}</span>
        </div>

        <div className="overflow-hidden rounded-md border">
          <table className="w-full table-fixed border-collapse bg-background">
            <thead className="bg-muted/40">
              <tr className="text-left text-sm text-muted-foreground">
                <th className="w-[28%] px-4 py-3 font-medium">{t("build.tagLibraryName", "标签库名称")}</th>
                <th className="px-4 py-3 font-medium">{t("build.description", "说明")}</th>
                <th className="w-[120px] px-4 py-3 font-medium">{t("build.tagCount", "标签数")}</th>
                <th className="w-[160px] px-4 py-3 font-medium">{t("build.operation", "操作")}</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td className="px-4 py-10 text-center text-sm text-muted-foreground" colSpan={4}>
                    {t("loading")}
                  </td>
                </tr>
              ) : rows.length === 0 ? (
                <tr>
                  <td className="px-4 py-10 text-center text-sm text-muted-foreground" colSpan={4}>
                    {t("build.empty", "暂无数据")}
                  </td>
                </tr>
              ) : (
                rows.map((row) => (
                  <tr key={row.id} className="border-t text-sm">
                    <td className="truncate px-4 py-3 font-medium">{row.name}</td>
                    <td className="truncate px-4 py-3 text-muted-foreground">{row.description || "--"}</td>
                    <td className="px-4 py-3">{row.tag_count}</td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1">
                        <Button variant="ghost" size="icon" onClick={() => openEdit(row)}>
                          <Pencil className="size-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          disabled={row.is_builtin}
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
