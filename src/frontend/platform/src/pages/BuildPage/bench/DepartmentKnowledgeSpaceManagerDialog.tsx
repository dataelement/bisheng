import { Checkbox } from "@/components/bs-ui/checkBox";
import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { SearchInput } from "@/components/bs-ui/input";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import {
  batchCreateDepartmentKnowledgeSpacesApi,
  getDepartmentKnowledgeSpacesApi,
  setDepartmentKnowledgeSpacesVisibilityApi,
} from "@/controllers/API/departmentKnowledgeSpace";
import { getDepartmentTreeApi } from "@/controllers/API/department";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import type { DepartmentTreeNode } from "@/types/api/department";
import { Building2, ChevronDown, ChevronRight, Plus } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onChanged?: () => void;
}

const TREE_INDENT_PER_LEVEL = 22;

function flattenDepartmentIds(nodes: DepartmentTreeNode[]): number[] {
  const ids: number[] = [];
  const walk = (list: DepartmentTreeNode[]) => {
    for (const node of list) {
      if (node.status !== "archived") ids.push(node.id);
      if (node.children?.length) walk(node.children);
    }
  };
  walk(nodes);
  return ids;
}

function findDepartmentNodeById(nodes: DepartmentTreeNode[], targetId: number): DepartmentTreeNode | null {
  for (const node of nodes) {
    if (node.id === targetId) return node;
    if (node.children?.length) {
      const hit = findDepartmentNodeById(node.children, targetId);
      if (hit) return hit;
    }
  }
  return null;
}

export function DepartmentKnowledgeSpaceManagerDialog({ open, onOpenChange, onChanged }: Props) {
  const { t } = useTranslation();
  const { toast } = useToast();
  const [tree, setTree] = useState<DepartmentTreeNode[]>([]);
  // department_id -> binding visibility. Includes hidden bindings so they can be restored.
  const [bindingByDept, setBindingByDept] = useState<Map<number, { isHidden: boolean }>>(new Map());
  const [selectedDeptIds, setSelectedDeptIds] = useState<Set<number>>(new Set());
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [keyword, setKeyword] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  const loadData = useCallback(async () => {
    setLoading(true);
    const [treeRes, spaceRes] = await Promise.all([
      captureAndAlertRequestErrorHoc(getDepartmentTreeApi()),
      captureAndAlertRequestErrorHoc(
        getDepartmentKnowledgeSpacesApi({ order_by: "name", include_hidden: true }),
      ),
    ]);
    if (treeRes && Array.isArray(treeRes)) {
      setTree(treeRes);
      setExpanded(new Set(treeRes.map((node) => node.id)));
    }
    const nextBindings = new Map<number, { isHidden: boolean }>();
    const visible = new Set<number>();
    if (spaceRes && Array.isArray(spaceRes)) {
      for (const item of spaceRes) {
        if (typeof item.department_id !== "number") continue;
        const isHidden = Boolean(item.is_hidden);
        nextBindings.set(item.department_id, { isHidden });
        if (!isHidden) visible.add(item.department_id);
      }
    }
    setBindingByDept(nextBindings);
    // Currently-displayed (visible-bound) departments start checked; toggling
    // them off stages a hide, toggling a hidden one on stages a restore.
    setSelectedDeptIds(visible);
    setLoading(false);
  }, []);

  useEffect(() => {
    if (!open) return;
    loadData();
  }, [open, loadData]);

  const matchesKeyword = (node: DepartmentTreeNode): boolean => {
    if (!keyword.trim()) return true;
    const lower = keyword.trim().toLowerCase();
    if (node.name.toLowerCase().includes(lower)) return true;
    return (node.children || []).some(matchesKeyword);
  };

  useEffect(() => {
    if (!keyword.trim()) return;
    const ids = new Set<number>();
    const walk = (nodes: DepartmentTreeNode[]) => {
      for (const node of nodes) {
        if (!matchesKeyword(node)) continue;
        ids.add(node.id);
        if (node.children?.length) walk(node.children);
      }
    };
    walk(tree);
    setExpanded((prev) => new Set([...prev, ...ids]));
  }, [keyword, tree]);

  const flatIds = useMemo(() => flattenDepartmentIds(tree), [tree]);

  const visibleBoundIds = useMemo(() => {
    const s = new Set<number>();
    bindingByDept.forEach((value, id) => {
      if (!value.isHidden) s.add(id);
    });
    return s;
  }, [bindingByDept]);

  const hiddenBoundIds = useMemo(() => {
    const s = new Set<number>();
    bindingByDept.forEach((value, id) => {
      if (value.isHidden) s.add(id);
    });
    return s;
  }, [bindingByDept]);

  // Departments that are not currently displayed: brand-new (create) or hidden
  // (restore). "Select all" only touches these, never the visible-bound ones,
  // so it can never mass-hide existing department spaces.
  const selectableForShowIds = useMemo(
    () => flatIds.filter((id) => !visibleBoundIds.has(id)),
    [flatIds, visibleBoundIds],
  );
  const allShowSelected =
    selectableForShowIds.length > 0 && selectableForShowIds.every((id) => selectedDeptIds.has(id));

  // Pending changes derived from the diff between current bindings and selection.
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

  const toggleSelectAll = () => {
    setSelectedDeptIds((prev) => {
      const next = new Set(prev);
      if (allShowSelected) {
        for (const id of selectableForShowIds) next.delete(id);
      } else {
        for (const id of selectableForShowIds) next.add(id);
      }
      return next;
    });
  };

  const toggleDept = (deptId: number) => {
    setSelectedDeptIds((prev) => {
      const next = new Set(prev);
      if (next.has(deptId)) next.delete(deptId);
      else next.add(deptId);
      return next;
    });
  };

  const handleSave = async () => {
    if (!hasChanges) return;
    setSaving(true);
    let ok = true;
    if (ok && pendingCreate.length) {
      const res = await captureAndAlertRequestErrorHoc(
        batchCreateDepartmentKnowledgeSpacesApi(pendingCreate),
      );
      if (!res) ok = false;
    }
    if (ok && pendingHide.length) {
      const res = await captureAndAlertRequestErrorHoc(
        setDepartmentKnowledgeSpacesVisibilityApi(pendingHide, true),
      );
      if (!res) ok = false;
    }
    if (ok && pendingRestore.length) {
      const res = await captureAndAlertRequestErrorHoc(
        setDepartmentKnowledgeSpacesVisibilityApi(pendingRestore, false),
      );
      if (!res) ok = false;
    }
    setSaving(false);
    onChanged?.();
    if (!ok) {
      // A request failed (already alerted); reload so local state matches reality.
      await loadData();
      return;
    }
    toast({
      title: t("prompt"),
      description: t("bench.departmentKnowledgeSpaceSaveSuccess", "保存成功"),
      variant: "success",
    });
    onOpenChange(false);
  };

  const renderNode = (node: DepartmentTreeNode, depth = 0) => {
    if (node.status === "archived" || !matchesKeyword(node)) return null;
    const hasChildren = node.children?.length > 0;
    const isExpanded = expanded.has(node.id);
    const isVisibleBound = visibleBoundIds.has(node.id);
    const isHiddenBound = hiddenBoundIds.has(node.id);
    const isSelected = selectedDeptIds.has(node.id);

    return (
      <div key={node.id}>
        <div
          data-depth={depth}
          className="group flex items-center rounded-md py-1.5 pr-2 hover:bg-[#F7F8FA]"
        >
          <div
            className="relative shrink-0 self-stretch"
            style={{ width: `${depth * TREE_INDENT_PER_LEVEL + 8}px` }}
            aria-hidden
          >
            {depth > 0 && (
              <span className="pointer-events-none absolute bottom-1 right-0 top-1 w-px bg-[#E5E6EB]" />
            )}
          </div>
          <button
            type="button"
            className="mr-2 inline-flex size-4 items-center justify-center text-[#86909C]"
            onClick={() => {
              if (!hasChildren) return;
              setExpanded((prev) => {
                const next = new Set(prev);
                if (next.has(node.id)) next.delete(node.id);
                else next.add(node.id);
                return next;
              });
            }}
          >
            {hasChildren ? (
              isExpanded ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />
            ) : (
              <span className="block size-4" />
            )}
          </button>
          <Checkbox checked={isSelected} onCheckedChange={() => toggleDept(node.id)} />
          <Building2 className="ml-2 size-4 shrink-0 text-[#86909C]" />
          <span className="min-w-0 flex-1 truncate text-sm text-[#1D2129]">{node.name}</span>
          {isVisibleBound && (
            <span className="rounded bg-[#E8F3FF] px-2 py-0.5 text-xs text-[#165DFF]">
              {t("bench.departmentKnowledgeSpaceConfigured", "已配置")}
            </span>
          )}
          {isHiddenBound && (
            <span className="rounded bg-[#F2F3F5] px-2 py-0.5 text-xs text-[#86909C]">
              {t("bench.departmentKnowledgeSpaceHidden", "已隐藏")}
            </span>
          )}
        </div>
        {hasChildren && isExpanded && (
          <div>{node.children.map((child) => renderNode(child, depth + 1))}</div>
        )}
      </div>
    );
  };

  const renderChangeGroup = (
    title: string,
    deptIds: number[],
    tone: string,
    withDefaultName: boolean,
  ) => {
    if (!deptIds.length) return null;
    return (
      <div>
        <p className="mb-2 text-xs font-medium text-[#4E5969]">
          {title}（{deptIds.length}）
        </p>
        <div className="space-y-2">
          {deptIds.map((deptId) => {
            const node = findDepartmentNodeById(tree, deptId);
            return (
              <div
                key={deptId}
                className="flex items-center justify-between rounded-md border border-[#E5E6EB] bg-white px-3 py-2"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className={`size-1.5 shrink-0 rounded-full ${tone}`} />
                    <span className="truncate text-sm text-[#1D2129]">{node?.name || deptId}</span>
                  </div>
                  {withDefaultName && (
                    <div className="mt-1 pl-3.5 text-xs text-[#86909C]">
                      {t("bench.departmentKnowledgeSpaceDefaultName", "默认空间名")}：
                      {node ? `${node.name}的知识空间` : ""}
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
            );
          })}
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
          <div className="rounded-lg border border-[#ECECEC] bg-white p-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <SearchInput
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                placeholder={t("bs:department.search")}
              />
              <Button variant="outline" onClick={toggleSelectAll}>
                {allShowSelected
                  ? t("bench.departmentKnowledgeSpaceClearAll", "取消全选")
                  : t("bench.departmentKnowledgeSpaceSelectAll", "全选可创建部门")}
              </Button>
            </div>
            <div className="max-h-[460px] overflow-y-auto">
              {loading ? (
                <div className="py-10 text-center text-sm text-[#86909C]">
                  {t("loading")}
                </div>
              ) : (
                tree.map((node) => renderNode(node))
              )}
            </div>
          </div>
          <div className="rounded-lg border border-[#ECECEC] bg-[#FAFBFC] p-4">
            <p className="text-sm font-medium text-[#1D2129]">
              {t("bench.departmentKnowledgeSpaceChangePreview", "变更预览")}
            </p>
            <p className="mt-1 text-sm text-[#86909C]">
              {t("bench.departmentKnowledgeSpaceSelectedDesc", "默认生成“XX部门的知识空间”，超级管理员为 owner，部门管理员默认为 manager。")}
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
