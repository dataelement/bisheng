import { LazyDepartmentTree, useLazyDepartmentTree } from "@/components/bs-comp/department";
import { Button } from "@/components/bs-ui/button";
import { Checkbox } from "@/components/bs-ui/checkBox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/bs-ui/dialog";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import {
  batchCreateDepartmentKnowledgeSpacesApi,
  getDepartmentKnowledgeSpacesApi,
  setDepartmentKnowledgeSpacesVisibilityApi,
} from "@/controllers/API/departmentKnowledgeSpace";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import type { DepartmentTreeNode } from "@/types/api/department";
import { Plus } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onChanged?: () => void;
}

type Binding = { isHidden: boolean; name: string };

export function DepartmentKnowledgeSpaceManagerDialog({ open, onOpenChange, onChanged }: Props) {
  const { t } = useTranslation();
  const { toast } = useToast();
  // F038: department tree is lazy now; only the (small) set of bound departments
  // and the user's in-session selection are tracked as id sets — never the whole
  // tree — so the create/hide/restore diff works without enumerating all depts.
  const tree = useLazyDepartmentTree({ includeArchived: false, autoLoad: open, autoExpandRoots: true });

  // department_id -> binding (visibility + name), including hidden ones so they can be restored.
  const [bindingByDept, setBindingByDept] = useState<Map<number, Binding>>(new Map());
  const [selectedDeptIds, setSelectedDeptIds] = useState<Set<number>>(new Set());
  const [saving, setSaving] = useState(false);
  // Names learned from the lazy tree as nodes render/toggle, so the change-preview
  // can label a pending department even when it isn't currently rendered.
  const nameRef = useRef<Map<number, string>>(new Map());

  const loadBindings = useCallback(async () => {
    const spaceRes = await captureAndAlertRequestErrorHoc(
      getDepartmentKnowledgeSpacesApi({ order_by: "name", include_hidden: true }),
    );
    const nextBindings = new Map<number, Binding>();
    const visible = new Set<number>();
    if (spaceRes && Array.isArray(spaceRes)) {
      for (const item of spaceRes) {
        if (typeof item.department_id !== "number") continue;
        const isHidden = Boolean(item.is_hidden);
        nextBindings.set(item.department_id, { isHidden, name: item.department_name || "" });
        if (item.department_name) nameRef.current.set(item.department_id, item.department_name);
        if (!isHidden) visible.add(item.department_id);
      }
    }
    setBindingByDept(nextBindings);
    // Visible-bound departments start checked; unchecking stages a hide, checking
    // a hidden one stages a restore.
    setSelectedDeptIds(visible);
  }, []);

  useEffect(() => {
    if (!open) return;
    void loadBindings();
  }, [open, loadBindings]);

  const visibleBoundIds = useMemo(() => {
    const s = new Set<number>();
    bindingByDept.forEach((v, id) => {
      if (!v.isHidden) s.add(id);
    });
    return s;
  }, [bindingByDept]);

  const hiddenBoundIds = useMemo(() => {
    const s = new Set<number>();
    bindingByDept.forEach((v, id) => {
      if (v.isHidden) s.add(id);
    });
    return s;
  }, [bindingByDept]);

  // Pending changes = diff between current bindings and the selection.
  const pendingCreate = useMemo(
    () => Array.from(selectedDeptIds).filter((id) => !bindingByDept.has(id)),
    [selectedDeptIds, bindingByDept],
  );
  const pendingRestore = useMemo(
    () => Array.from(selectedDeptIds).filter((id) => hiddenBoundIds.has(id)),
    [selectedDeptIds, hiddenBoundIds],
  );
  const pendingHide = useMemo(
    () => Array.from(visibleBoundIds).filter((id) => !selectedDeptIds.has(id)),
    [visibleBoundIds, selectedDeptIds],
  );
  const hasChanges = pendingCreate.length + pendingRestore.length + pendingHide.length > 0;

  const nameOf = (id: number) => nameRef.current.get(id) || bindingByDept.get(id)?.name || String(id);

  const toggleDept = (node: DepartmentTreeNode | number) => {
    const id = typeof node === "number" ? node : node.id;
    if (typeof node !== "number") nameRef.current.set(node.id, node.name);
    setSelectedDeptIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  // F038: "select all" now spans the LOADED departments only (lazy tree). Mass-
  // binding tens of thousands of departments isn't a real workflow; the curated
  // create/hide flow per browsed node is the intended path.
  const loadedSelectableIds = useMemo(() => {
    const out: number[] = [];
    const walk = (ids: number[]) => {
      for (const id of ids) {
        if (!visibleBoundIds.has(id)) out.push(id);
        const kids = tree.getChildIds(id);
        if (kids) walk(kids);
      }
    };
    walk(tree.rootIds);
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tree.rootIds, tree.expanded, visibleBoundIds]);

  const allShowSelected =
    loadedSelectableIds.length > 0 && loadedSelectableIds.every((id) => selectedDeptIds.has(id));

  const toggleSelectAll = () => {
    // Record names of everything we touch so the preview can label them.
    for (const id of loadedSelectableIds) {
      const node = tree.getNode(id);
      if (node) nameRef.current.set(id, node.name);
    }
    setSelectedDeptIds((prev) => {
      const next = new Set(prev);
      if (allShowSelected) for (const id of loadedSelectableIds) next.delete(id);
      else for (const id of loadedSelectableIds) next.add(id);
      return next;
    });
  };

  const handleSave = async () => {
    if (!hasChanges) return;
    setSaving(true);
    let ok = true;
    if (ok && pendingCreate.length) {
      const res = await captureAndAlertRequestErrorHoc(batchCreateDepartmentKnowledgeSpacesApi(pendingCreate));
      if (!res) ok = false;
    }
    if (ok && pendingHide.length) {
      const res = await captureAndAlertRequestErrorHoc(setDepartmentKnowledgeSpacesVisibilityApi(pendingHide, true));
      if (!res) ok = false;
    }
    if (ok && pendingRestore.length) {
      const res = await captureAndAlertRequestErrorHoc(setDepartmentKnowledgeSpacesVisibilityApi(pendingRestore, false));
      if (!res) ok = false;
    }
    setSaving(false);
    onChanged?.();
    if (!ok) {
      await loadBindings();
      return;
    }
    toast({
      title: t("prompt"),
      description: t("bench.departmentKnowledgeSpaceSaveSuccess", "保存成功"),
      variant: "success",
    });
    onOpenChange(false);
  };

  const renderRowPrefix = (node: DepartmentTreeNode) => (
    <Checkbox
      className="mr-1.5 shrink-0"
      checked={selectedDeptIds.has(node.id)}
      onClick={(e) => e.stopPropagation()}
      onCheckedChange={() => toggleDept(node)}
    />
  );

  const renderRowSuffix = (node: DepartmentTreeNode) => {
    if (visibleBoundIds.has(node.id)) {
      return (
        <span className="ml-auto shrink-0 rounded bg-[#E8F3FF] px-2 py-0.5 text-xs text-[#165DFF]">
          {t("bench.departmentKnowledgeSpaceConfigured", "已配置")}
        </span>
      );
    }
    if (hiddenBoundIds.has(node.id)) {
      return (
        <span className="ml-auto shrink-0 rounded bg-[#F2F3F5] px-2 py-0.5 text-xs text-[#86909C]">
          {t("bench.departmentKnowledgeSpaceHidden", "已隐藏")}
        </span>
      );
    }
    return null;
  };

  const renderChangeGroup = (title: string, deptIds: number[], tone: string, withDefaultName: boolean) => {
    if (!deptIds.length) return null;
    return (
      <div>
        <p className="mb-2 text-xs font-medium text-[#4E5969]">
          {title}（{deptIds.length}）
        </p>
        <div className="space-y-2">
          {deptIds.map((deptId) => (
            <div
              key={deptId}
              className="flex items-center justify-between rounded-md border border-[#E5E6EB] bg-white px-3 py-2"
            >
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className={`size-1.5 shrink-0 rounded-full ${tone}`} />
                  <span className="truncate text-sm text-[#1D2129]">{nameOf(deptId)}</span>
                </div>
                {withDefaultName && (
                  <div className="mt-1 pl-3.5 text-xs text-[#86909C]">
                    {t("bench.departmentKnowledgeSpaceDefaultName", "默认空间名")}：{`${nameOf(deptId)}的知识空间`}
                  </div>
                )}
              </div>
              <button
                type="button"
                className="text-[#86909C] hover:text-[#F53F3F]"
                onClick={() => toggleDept(deptId)}
              >
                <Plus className="size-4 rotate-45" />
              </button>
            </div>
          ))}
        </div>
      </div>
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[920px]">
        <DialogHeader>
          <DialogTitle>{t("bench.departmentKnowledgeSpaceManager", "部门知识空间管理")}</DialogTitle>
          <DialogDescription>
            {t(
              "bench.departmentKnowledgeSpaceManagerDesc2",
              "勾选部门创建知识空间，取消勾选已配置部门可将其从列表隐藏（不会删除空间与数据）。",
            )}
          </DialogDescription>
        </DialogHeader>
        <div className="grid grid-cols-[1.1fr_0.9fr] gap-5 py-2">
          <div className="flex h-[460px] flex-col rounded-lg border border-[#ECECEC] bg-white p-4">
            <div className="mb-3 flex shrink-0 justify-end">
              <Button variant="outline" onClick={toggleSelectAll}>
                {allShowSelected
                  ? t("bench.departmentKnowledgeSpaceClearAll", "取消全选")
                  : t("bench.departmentKnowledgeSpaceSelectAll", "全选可创建部门")}
              </Button>
            </div>
            <LazyDepartmentTree
              controller={tree}
              renderRowPrefix={renderRowPrefix}
              renderRowSuffix={renderRowSuffix}
              searchPlaceholder={t("bs:department.search")}
            />
          </div>
          <div className="rounded-lg border border-[#ECECEC] bg-[#FAFBFC] p-4">
            <p className="text-sm font-medium text-[#1D2129]">
              {t("bench.departmentKnowledgeSpaceChangePreview", "变更预览")}
            </p>
            <p className="mt-1 text-sm text-[#86909C]">
              {t(
                "bench.departmentKnowledgeSpaceSelectedDesc",
                "默认生成“XX部门的知识空间”，超级管理员为 owner，部门管理员默认为 manager。",
              )}
            </p>
            <div className="mt-4 max-h-[380px] space-y-4 overflow-y-auto">
              {!hasChanges ? (
                <div className="rounded-lg border border-dashed border-[#D9DDE5] bg-white px-4 py-8 text-center text-sm text-[#86909C]">
                  {t("bench.departmentKnowledgeSpaceNoChanges", "暂无变更")}
                </div>
              ) : (
                <>
                  {renderChangeGroup(
                    t("bench.departmentKnowledgeSpacePendingCreate", "待创建"),
                    pendingCreate,
                    "bg-[#00B42A]",
                    true,
                  )}
                  {renderChangeGroup(
                    t("bench.departmentKnowledgeSpacePendingRestore", "待恢复显示"),
                    pendingRestore,
                    "bg-[#165DFF]",
                    false,
                  )}
                  {renderChangeGroup(
                    t("bench.departmentKnowledgeSpacePendingHide", "待隐藏"),
                    pendingHide,
                    "bg-[#F53F3F]",
                    false,
                  )}
                </>
              )}
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button disabled={saving || !hasChanges} onClick={handleSave}>
            {t("bench.departmentKnowledgeSpaceSave", "保存")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
