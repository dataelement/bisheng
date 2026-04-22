import { Checkbox } from "@/components/bs-ui/checkBox";
import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { SearchInput } from "@/components/bs-ui/input";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { batchCreateDepartmentKnowledgeSpacesApi, getDepartmentKnowledgeSpacesApi } from "@/controllers/API/departmentKnowledgeSpace";
import { getDepartmentTreeApi } from "@/controllers/API/department";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import type { DepartmentTreeNode } from "@/types/api/department";
import { Building2, ChevronDown, ChevronRight, Plus } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated?: () => void;
}

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

export function DepartmentKnowledgeSpaceManagerDialog({ open, onOpenChange, onCreated }: Props) {
  const { t } = useTranslation();
  const { toast } = useToast();
  const [tree, setTree] = useState<DepartmentTreeNode[]>([]);
  const [configuredDeptIds, setConfiguredDeptIds] = useState<Set<number>>(new Set());
  const [selectedDeptIds, setSelectedDeptIds] = useState<Set<number>>(new Set());
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [keyword, setKeyword] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    Promise.all([
      captureAndAlertRequestErrorHoc(getDepartmentTreeApi()),
      captureAndAlertRequestErrorHoc(getDepartmentKnowledgeSpacesApi({ order_by: "name" })),
    ]).then(([treeRes, spaceRes]) => {
      if (treeRes && Array.isArray(treeRes)) {
        setTree(treeRes);
        setExpanded(new Set(treeRes.map((node) => node.id)));
      }
      if (spaceRes && Array.isArray(spaceRes)) {
        setConfiguredDeptIds(new Set(
          spaceRes
            .map((item) => item.department_id)
            .filter((id): id is number => typeof id === "number")
        ));
      }
      setSelectedDeptIds(new Set());
      setLoading(false);
    });
  }, [open]);

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
  const selectableIds = useMemo(
    () => flatIds.filter((id) => !configuredDeptIds.has(id)),
    [flatIds, configuredDeptIds],
  );

  const toggleSelectAll = () => {
    if (selectedDeptIds.size === selectableIds.length) {
      setSelectedDeptIds(new Set());
      return;
    }
    setSelectedDeptIds(new Set(selectableIds));
  };

  const toggleDept = (deptId: number) => {
    if (configuredDeptIds.has(deptId)) return;
    setSelectedDeptIds((prev) => {
      const next = new Set(prev);
      if (next.has(deptId)) next.delete(deptId);
      else next.add(deptId);
      return next;
    });
  };

  const handleCreate = async () => {
    if (selectedDeptIds.size === 0) {
      toast({
        title: t("prompt"),
        description: t("bench.departmentKnowledgeSpaceSelectDepartment", "请选择至少一个部门"),
        variant: "error",
      });
      return;
    }
    setSaving(true);
    const res = await captureAndAlertRequestErrorHoc(
      batchCreateDepartmentKnowledgeSpacesApi(Array.from(selectedDeptIds)),
    );
    setSaving(false);
    if (!res) return;
    toast({
      title: t("prompt"),
      description: t("bench.departmentKnowledgeSpaceCreateSuccess", "部门知识空间创建成功"),
      variant: "success",
    });
    onCreated?.();
    onOpenChange(false);
  };

  const renderNode = (node: DepartmentTreeNode, depth = 0) => {
    if (node.status === "archived" || !matchesKeyword(node)) return null;
    const hasChildren = node.children?.length > 0;
    const isExpanded = expanded.has(node.id);
    const isConfigured = configuredDeptIds.has(node.id);
    const isSelected = selectedDeptIds.has(node.id);

    return (
      <div key={node.id}>
        <div
          className="group flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-[#F7F8FA]"
          style={{ paddingLeft: `${depth * 18 + 8}px` }}
        >
          <button
            type="button"
            className="inline-flex size-4 items-center justify-center text-[#86909C]"
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
          <Checkbox
            checked={isConfigured ? true : isSelected}
            disabled={isConfigured}
            onCheckedChange={() => toggleDept(node.id)}
          />
          <Building2 className="size-4 text-[#86909C]" />
          <span className="min-w-0 flex-1 truncate text-sm text-[#1D2129]">{node.name}</span>
          {isConfigured && (
            <span className="rounded bg-[#E8F3FF] px-2 py-0.5 text-xs text-[#165DFF]">
              {t("bench.departmentKnowledgeSpaceConfigured", "已配置")}
            </span>
          )}
        </div>
        {hasChildren && isExpanded && (
          <div>{node.children.map((child) => renderNode(child, depth + 1))}</div>
        )}
      </div>
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[920px]">
        <DialogHeader>
          <DialogTitle>{t("bench.departmentKnowledgeSpaceManager", "部门知识空间管理")}</DialogTitle>
          <DialogDescription>
            {t("bench.departmentKnowledgeSpaceManagerDesc", "选择未绑定知识空间的部门，批量创建部门知识空间。")}
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
                {selectedDeptIds.size === selectableIds.length
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
              {t("bench.departmentKnowledgeSpaceSelected", "待创建部门")}
            </p>
            <p className="mt-1 text-sm text-[#86909C]">
              {t("bench.departmentKnowledgeSpaceSelectedDesc", "默认生成“XX部门的知识空间”，超级管理员为 owner，部门管理员默认为 manager。")}
            </p>
            <div className="mt-4 max-h-[380px] space-y-2 overflow-y-auto">
              {Array.from(selectedDeptIds).length === 0 ? (
                <div className="rounded-lg border border-dashed border-[#D9DDE5] bg-white px-4 py-8 text-center text-sm text-[#86909C]">
                  {t("bench.departmentKnowledgeSpaceEmptySelection", "请选择左侧部门")}
                </div>
              ) : (
                Array.from(selectedDeptIds).map((deptId) => {
                  const findNode = (nodes: DepartmentTreeNode[]): DepartmentTreeNode | null => {
                    for (const node of nodes) {
                      if (node.id === deptId) return node;
                      const hit = node.children?.length ? findNode(node.children) : null;
                      if (hit) return hit;
                    }
                    return null;
                  };
                  const node = findNode(tree);
                  return (
                    <div key={deptId} className="flex items-center justify-between rounded-md border border-[#E5E6EB] bg-white px-3 py-2">
                      <div className="min-w-0">
                        <div className="truncate text-sm text-[#1D2129]">{node?.name || deptId}</div>
                        <div className="mt-1 text-xs text-[#86909C]">
                          {t("bench.departmentKnowledgeSpaceDefaultName", "默认空间名")}：{node ? `${node.name}的知识空间` : ""}
                        </div>
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
                })
              )}
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button disabled={saving || selectedDeptIds.size === 0} onClick={handleCreate}>
            {t("bench.departmentKnowledgeSpaceCreate", "创建")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
