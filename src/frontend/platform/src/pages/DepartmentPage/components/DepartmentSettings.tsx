// @ts-strict-ignore
import { notification } from '@bisheng/ui';
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { DepartmentSettingsView } from "./DepartmentSettingsView";

import { DepartmentUserOption } from "@/components/bs-comp/selectComponent/DepartmentUsersSelect";

import {
  deleteDepartmentApi,
  getDepartmentAdminsApi,
  getDepartmentApi,
  getDepartmentAssignableRolesApi,
  getDepartmentChildrenApi,
  getDepartmentPathTreeApi,
  moveDepartmentApi,
  purgeDepartmentApi,
  restoreDepartmentApi,
  updateDepartmentApi,
} from "@/controllers/API/department";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { isSyncedSource } from "@/pages/DepartmentPage/constants/syncReadonly";
import type { DepartmentAdmin, DepartmentSearchResult, DepartmentTreeNode } from "@/types/api/department";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

interface DepartmentSettingsProps {
  dept: DepartmentTreeNode;
  onChanged: (removedDeptId?: string) => void;
  /** Open the "mark as Child Tenant" dialog for this department. When undefined
   * (multi-tenant disabled or root dept), the action button is hidden. */
  onMarkAsTenant?: (deptId: number, deptName: string) => void;
}

function adminsToOptions(admins: DepartmentAdmin[]): DepartmentUserOption[] {
  return admins.map((a) => ({ value: Number(a.user_id), label: a.user_name }));
}

function sameIdSet(left: Array<number | string>, right: Array<number | string>): boolean {
  if (left.length !== right.length) return false;
  const leftIds = left.map(String).sort();
  const rightIds = right.map(String).sort();
  return leftIds.every((id, idx) => id === rightIds[idx]);
}

/** 企业级表单：统一控件最大宽度，右侧对齐 */
const FORM_CONTROL_WIDTH = "w-full max-w-md";

export function useDepartmentSettingsController({ dept, onChanged, onMarkAsTenant }: DepartmentSettingsProps) {
  const { t } = useTranslation();
  const [name, setName] = useState(dept.name);
  const [adminSelectValue, setAdminSelectValue] = useState<DepartmentUserOption[]>([]);
  const [defaultRoleIds, setDefaultRoleIds] = useState<string[]>([]);
  const [applyDefaultRolesToExisting, setApplyDefaultRolesToExisting] = useState(false);
  const [assignableRoles, setAssignableRoles] = useState<{ value: string; label: string }[]>([]);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [parentIdValue, setParentIdValue] = useState<number | null>(dept.parent_id ?? null);
  // F038: the full tree is no longer passed in. ``isVisibleRootDept`` is derived
  // from the root layer; ``parentDisplayName`` from a path-tree lookup (used for
  // the read-only parent field when the parent can't be edited).
  const [isVisibleRootDept, setIsVisibleRootDept] = useState(false);
  // Whether the visible-root determination (below) has completed for the current
  // dept. ``isVisibleRootDept`` starts false, so without this gate the editable
  // parent picker would mount for one render on a visible-root dept and locate its
  // OUT-OF-SCOPE parent via path-tree (21009). Keep the parent read-only until we
  // actually know whether this dept is a root.
  const [visibleRootResolved, setVisibleRootResolved] = useState(false);
  const [parentDisplayName, setParentDisplayName] = useState("-");

  const adminSelectValueRef = useRef<DepartmentUserOption[]>([]);

  const isSynced = isSyncedSource(dept.source);
  const isArchived = dept.status === "archived";
  const isAbsoluteRootDept = dept.parent_id === null || Number(dept.parent_id) === 0;
  // 对部门管理员场景：当前可见树的顶层节点也视为“根节点”（即便全局树里它还有父节点）。
  // 租户根部门同样按“根”对待：其父是系统根——对租户管理员越权、对任何角色都无展示意义，
  // 故隐藏“上级部门”字段、不取父名、也不允许移动（与查看者角色无关）。
  const isRootDept = isAbsoluteRootDept || isVisibleRootDept || !!dept.is_tenant_root;
  /** 仅部门名称对第三方同步部门只读；管理员与默认角色仍可保存 */
  const canEditName = !isArchived && !isSynced;
  const canEditPermissions = !isArchived;
  const canEditParent = !isArchived && !isSynced && !isRootDept && visibleRootResolved;

  /** 最近一次从服务端加载成功的快照（父部门变更判断、保存后更新） */
  const baselineRef = useRef<{
    name: string;
    admins: DepartmentUserOption[];
    defaultRoleIds: string[];
    parentId: number | null;
  } | null>(null);

  useEffect(() => {
    adminSelectValueRef.current = adminSelectValue;
  }, [adminSelectValue]);

  // F038: resolve "is this the top of the viewer's visible tree?" from the root
  // layer, and the parent's display name from a path-tree lookup — replacing the
  // walks over a full tree that's no longer passed in. The move picker forbids
  // selecting the dept's own subtree via excludeSubtreePath={dept.path} instead.
  useEffect(() => {
    let cancelled = false;
    // Re-defer the editable parent picker until this dept's root-ness is known.
    setVisibleRootResolved(false);
    if (dept.parent_id == null || dept.is_tenant_root) {
      // Absolute root, or a tenant root whose parent is the system root: there is
      // no in-scope / meaningful parent to resolve. ``isRootDept`` already covers
      // both via ``is_tenant_root`` so the parent field is hidden — skip the fetch
      // entirely (a tenant admin would be denied; a super admin doesn't need it).
      setIsVisibleRootDept(false);
      setParentDisplayName("-");
      setVisibleRootResolved(true);
      return;
    }
    captureAndAlertRequestErrorHoc(getDepartmentChildrenApi(null)).then((roots) => {
      if (cancelled) return;
      const visibleRoot = Array.isArray(roots) && roots.some((n) => n.id === dept.id);
      setIsVisibleRootDept(visibleRoot);
      setVisibleRootResolved(true);
      // When the dept sits at the top of the viewer's visible tree, its parent is
      // OUTSIDE the viewer's scope (e.g. a sub-tenant admin's tenant-root dept,
      // whose parent is the global root). Fetching that parent's path-tree would
      // be denied (21009) — skip it and leave the read-only parent field blank.
      // A nested dept's parent is always in scope, so it is safe to resolve.
      if (visibleRoot) {
        setParentDisplayName("-");
        return;
      }
      captureAndAlertRequestErrorHoc(getDepartmentPathTreeApi(dept.parent_id!)).then((res) => {
        if (cancelled) return;
        const pruned = (res as DepartmentSearchResult | null) ?? null;
        let cur = pruned?.roots?.[0];
        let name = "-";
        while (cur) {
          name = cur.name;
          cur = cur.children?.[0];
        }
        setParentDisplayName(name);
      });
    });
    return () => {
      cancelled = true;
    };
  }, [dept.id, dept.parent_id, dept.is_tenant_root]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setApplyDefaultRolesToExisting(false);
    Promise.all([
      getDepartmentAdminsApi(dept.dept_id),
      getDepartmentApi(dept.dept_id),
      getDepartmentAssignableRolesApi(dept.dept_id),
    ])
      .then(([adminsRes, detailRes, rolesRes]) => {
        if (cancelled) return;
        const adm = Array.isArray(adminsRes) ? adminsRes : [];
        const adminOpts = adminsToOptions(adm);
        setAdminSelectValue(adminOpts);
        adminSelectValueRef.current = adminOpts;
        setName(detailRes?.name ?? dept.name);
        const dr = (detailRes?.default_role_ids ?? []).map(String);
        setDefaultRoleIds(dr);
        const pid = detailRes?.parent_id ?? dept.parent_id ?? null;
        setParentIdValue(pid);
        setAssignableRoles((rolesRes || []).map((r) => ({ value: String(r.id), label: r.role_name })));
        baselineRef.current = {
          name: detailRes?.name ?? dept.name,
          admins: adminOpts,
          defaultRoleIds: dr,
          parentId: pid,
        };
      })
      .catch(() => {
        if (!cancelled) {
          notification.open({ type: "error", title: String(t("prompt") ?? ''), description: String(t("bs:department.settingsLoadFailed") ?? '') });
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [dept.dept_id, dept.name, dept.parent_id, t]);

  const restoreBaseline = useCallback((b = baselineRef.current) => {
    if (!b) return;
    setName(b.name);
    setAdminSelectValue(b.admins);
    adminSelectValueRef.current = b.admins;
    setDefaultRoleIds(b.defaultRoleIds);
    setParentIdValue(b.parentId);
  }, []);

  const hasUnsavedSettingsChanges = useCallback(() => {
    const b = baselineRef.current;
    if (!b) return false;
    if (canEditName && name !== b.name) return true;
    if (canEditParent && parentIdValue !== b.parentId) return true;
    if (
      !sameIdSet(
        adminSelectValue.map((o) => o.value),
        b.admins.map((o) => o.value),
      )
    )
      return true;
    if (!sameIdSet(defaultRoleIds, b.defaultRoleIds)) return true;
    return false;
  }, [adminSelectValue, canEditName, canEditParent, defaultRoleIds, name, parentIdValue]);

  const handleCancel = useCallback(() => {
    const b = baselineRef.current;
    if (!b) return;
    if (!hasUnsavedSettingsChanges()) {
      restoreBaseline(b);
      return;
    }
    bsConfirm({
      title: t("prompt"),
      desc: t("department.confirmCancelSettings", { ns: "bs" }),
      onOk: (next) => {
        restoreBaseline(b);
        next();
      },
    });
  }, [hasUnsavedSettingsChanges, restoreBaseline, t]);

  const handleGlobalSave = useCallback(async () => {
    if (!canEditPermissions) return;
    if (canEditName && (!name || name.length < 2 || name.length > 50)) {
      notification.open({ type: "error", title: String(t("prompt") ?? ''), description: String(t("bs:department.nameLength") ?? '') });
      return;
    }
    setSaving(true);
    try {
      const body: {
        name?: string;
        default_role_ids?: number[];
        admin_user_ids?: number[];
        apply_default_roles_to_existing_members?: boolean;
      } = {};
      const baseline = baselineRef.current;
      const nextName = name.trim();
      const nextAdminIds = adminSelectValue.map((o) => o.value);
      const nextDefaultRoleIds = defaultRoleIds.map(Number);
      if (canEditName && baseline && nextName !== baseline.name) {
        body.name = nextName;
      }
      if (
        baseline &&
        !sameIdSet(
          nextAdminIds,
          baseline.admins.map((o) => o.value),
        )
      ) {
        body.admin_user_ids = nextAdminIds;
      }
      if (baseline && !sameIdSet(nextDefaultRoleIds, baseline.defaultRoleIds)) {
        body.default_role_ids = nextDefaultRoleIds;
      }
      if (applyDefaultRolesToExisting) {
        body.apply_default_roles_to_existing_members = true;
      }
      const nextParentId = parentIdValue;
      const parentChanged = canEditParent && baseline && nextParentId !== null && nextParentId !== baseline.parentId;

      if (!parentChanged && Object.keys(body).length === 0) {
        return;
      }

      if (parentChanged) {
        const moveRes = await captureAndAlertRequestErrorHoc(moveDepartmentApi(dept.dept_id, nextParentId));
        if (moveRes === null || moveRes === false) return;
      }
      const res = await captureAndAlertRequestErrorHoc(updateDepartmentApi(dept.dept_id, body));
      if (res === null || res === false) return;
      notification.open({ type: "success", title: String(t("prompt") ?? ''), description: String(t("saved") ?? '') });
      setApplyDefaultRolesToExisting(false);
      const nextAdmins = await getDepartmentAdminsApi(dept.dept_id).catch(() => null);
      const adminOpts = Array.isArray(nextAdmins) ? adminsToOptions(nextAdmins) : adminSelectValue;
      setAdminSelectValue(adminOpts);
      adminSelectValueRef.current = adminOpts;
      baselineRef.current = {
        name: nextName,
        admins: adminOpts,
        defaultRoleIds: [...defaultRoleIds],
        parentId: nextParentId ?? baselineRef.current?.parentId ?? dept.parent_id ?? null,
      };
      onChanged();
    } finally {
      setSaving(false);
    }
  }, [
    adminSelectValue,
    canEditName,
    canEditParent,
    canEditPermissions,
    applyDefaultRolesToExisting,
    defaultRoleIds,
    dept.dept_id,
    dept.parent_id,
    name,
    onChanged,
    parentIdValue,
    t,
  ]);

  const handleDelete = useCallback(() => {
    bsConfirm({
      title: t("bs:department.delete"),
      desc: t("bs:department.confirmDelete"),
      onOk: (next) => {
        captureAndAlertRequestErrorHoc(deleteDepartmentApi(dept.dept_id)).then((res) => {
          if (res !== false && res !== "canceled") {
            notification.open({ type: "success", title: String(t("prompt") ?? ''), description: String(t("deleteSuccess") ?? '') });
            onChanged();
          }
          next();
        });
      },
    });
  }, [dept.dept_id, onChanged, t]);

  const handlePurge = useCallback(() => {
    bsConfirm({
      title: t("bs:department.permanentDelete"),
      desc: t("bs:department.confirmPermanentDelete"),
      onOk: (next) => {
        captureAndAlertRequestErrorHoc(purgeDepartmentApi(dept.dept_id)).then((res) => {
          if (res !== false && res !== "canceled") {
            notification.open({ type: "success", title: String(t("prompt") ?? ''), description: String(t("deleteSuccess") ?? '') });
            onChanged(dept.dept_id);
          }
          next();
        });
      },
    });
  }, [dept.dept_id, onChanged, t]);

  const handleRestore = useCallback(() => {
    bsConfirm({
      title: t("bs:department.restore"),
      desc: t("bs:department.confirmRestore"),
      onOk: (next) => {
        captureAndAlertRequestErrorHoc(restoreDepartmentApi(dept.dept_id)).then((res) => {
          if (res !== false && res !== "canceled") {
            notification.open({ type: "success", title: String(t("prompt") ?? ''), description: String(t("save") + t("success")) });
            onChanged();
          }
          next();
        });
      },
    });
  }, [dept.dept_id, onChanged, t]);

  return {
    FORM_CONTROL_WIDTH,
    handleRestore,
    isArchived,
    t,
    loading,
    isSynced,
    name,
    setName,
    isRootDept,
    canEditParent,
    parentIdValue,
    setParentIdValue,
    dept,
    parentDisplayName,
    canEditPermissions,
    adminSelectValue,
    setAdminSelectValue,
    adminSelectValueRef,
    defaultRoleIds,
    assignableRoles,
    setDefaultRoleIds,
    applyDefaultRolesToExisting,
    setApplyDefaultRolesToExisting,
    handlePurge,
    handleGlobalSave,
    saving,
    onMarkAsTenant,
    onChanged,
    handleDelete,
  };
}
export function DepartmentSettings(props: DepartmentSettingsProps) {
  return <DepartmentSettingsView controller={useDepartmentSettingsController(props)} />;
}
