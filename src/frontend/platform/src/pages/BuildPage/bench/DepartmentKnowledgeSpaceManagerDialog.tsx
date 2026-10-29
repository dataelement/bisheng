import { Button, notification } from '@bisheng/ui';
import { LazyDepartmentTree, useLazyDepartmentTree } from "@/components/bs-comp/department";

import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/bs-ui/dialog";

import {
    batchCreateDepartmentKnowledgeSpacesApi,
    getDepartmentKnowledgeSpacesApi,
    setDepartmentKnowledgeSpacesVisibilityApi,
} from "@/controllers/API/departmentKnowledgeSpace";
import { showApiError } from "@/controllers/request";
import type { DepartmentTreeNode } from "@/types/api/department";
import { Checkbox } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";

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
        const spaceRes = await getDepartmentKnowledgeSpacesApi({ order_by: "name", include_hidden: true });
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
        void loadBindings().catch(showApiError);
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
        try {
        if (pendingCreate.length) {
            await batchCreateDepartmentKnowledgeSpacesApi(pendingCreate);
        }
        if (pendingHide.length) {
            await setDepartmentKnowledgeSpacesVisibilityApi(pendingHide, true);
        }
        if (pendingRestore.length) {
            await setDepartmentKnowledgeSpacesVisibilityApi(pendingRestore, false);
        }
        onChanged?.();
        notification.open({ type: "success", title: String(t("prompt") ?? ''), description: String(t("bench.departmentKnowledgeSpaceSaveSuccess") ?? '') });
        onOpenChange(false);
        } catch (error) {
            showApiError(error);
        } finally {
            setSaving(false);
        }
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
                    {t("bench.departmentKnowledgeSpaceConfigured")}
                </span>
            );
        }
        if (hiddenBoundIds.has(node.id)) {
            return (
                <span className="ml-auto shrink-0 rounded bg-[#F2F3F5] px-2 py-0.5 text-xs text-[#86909C]">
                    {t("bench.departmentKnowledgeSpaceHidden")}
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
                                        {t("bench.departmentKnowledgeSpaceDefaultName")}：
                                        {`${nameOf(deptId)}的知识空间`}
                                    </div>
                                )}
                            </div>
                            <Button type="button" variant="text" onClick={() => toggleDept(deptId)} color="default">
                                <Outlined.Plus className="size-4 rotate-45" />
                            </Button>
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
                    <DialogTitle>{t("bench.departmentKnowledgeSpaceManager")}</DialogTitle>
                    <DialogDescription>{t("bench.departmentKnowledgeSpaceManagerDesc2")}</DialogDescription>
                </DialogHeader>
                <div className="grid grid-cols-[1.1fr_0.9fr] gap-5 py-2">
                    <div className="flex h-[460px] flex-col rounded-lg border border-[#ECECEC] bg-white p-4">
                        <div className="mb-3 flex shrink-0 justify-end">
                            <Button variant="outlined" onClick={toggleSelectAll} color="default">
                                {allShowSelected
                                    ? t("bench.departmentKnowledgeSpaceClearAll")
                                    : t("bench.departmentKnowledgeSpaceSelectAll")}
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
                            {t("bench.departmentKnowledgeSpaceChangePreview")}
                        </p>
                        <p className="mt-1 text-sm text-[#86909C]">{t("bench.departmentKnowledgeSpaceSelectedDesc")}</p>
                        <div className="mt-4 max-h-[380px] space-y-4 overflow-y-auto">
                            {!hasChanges ? (
                                <div className="rounded-lg border border-dashed border-[#D9DDE5] bg-white px-4 py-8 text-center text-sm text-[#86909C]">
                                    {t("bench.departmentKnowledgeSpaceNoChanges")}
                                </div>
                            ) : (
                                <>
                                    {renderChangeGroup(
                                        t("bench.departmentKnowledgeSpacePendingCreate"),
                                        pendingCreate,
                                        "bg-[#00B42A]",
                                        true,
                                    )}
                                    {renderChangeGroup(
                                        t("bench.departmentKnowledgeSpacePendingRestore"),
                                        pendingRestore,
                                        "bg-[#165DFF]",
                                        false,
                                    )}
                                    {renderChangeGroup(
                                        t("bench.departmentKnowledgeSpacePendingHide"),
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
                    <Button variant="outlined" onClick={() => onOpenChange(false)} color="default">
                        {t("cancel")}
                    </Button>
                    <Button disabled={saving || !hasChanges} onClick={handleSave}>
                        {t("bench.departmentKnowledgeSpaceSave")}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
