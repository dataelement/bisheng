import { toast } from '@bisheng/ui';
import { RolesView } from "./RolesView";

import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";

import { useResizableColumns } from "@/components/bs-ui/table/useResizableColumns";

import { userContext } from "@/contexts/userContext";
import { getDepartmentChildrenApi } from "@/controllers/API/department";
import {
  createRoleV2Api,
  deleteRoleV2Api,
  getRoleMenuV2Api,
  getRolesPageApi,
  updateRoleV2Api,
} from "@/controllers/API/user";
import { showApiError } from "@/controllers/request";
import { DepartmentTreeNode } from "@/types/api/department";
import { ROLE } from "@/types/api/user";
import { useContext, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  CHILD_DEPENDENTS,
  DEFAULT_ENABLED_MENU_IDS,
  normalizeRoleMenuSelection,
} from "./roleMenuSelection";
import {
  buildRoleQuotaConfig,
  createDefaultRoleQuota,
  formatRoleQuotaCount,
  formatRoleQuotaGb,
  parseRoleQuota,
  ROLE_QUOTA_DEFAULT_CHANNEL,
  ROLE_QUOTA_DEFAULT_SPACE_CREATE,
  RoleQuotaState,
  serializeRoleQuotaSnapshot,
  validateRoleQuota,
} from "./roleQuotaConfig";

export function useRolesController() {
  const { t } = useTranslation();
  const { user } = useContext(userContext);
  const isPlatformAdmin = user?.is_global_super === true || user?.role === "admin";

  const [roles, setRoles] = useState<ROLE[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [keyword, setKeyword] = useState("");
  const [deptTree, setDeptTree] = useState<DepartmentTreeNode[]>([]);
  const [editOpen, setEditOpen] = useState(false);
  const [activeRole, setActiveRole] = useState<ROLE | null>(null);
  const [roleName, setRoleName] = useState("");
  const [roleType, setRoleType] = useState<"tenant" | "global">("tenant");
  const [departmentId, setDepartmentId] = useState<string>("none");
  const [quota, setQuota] = useState<RoleQuotaState>(createDefaultRoleQuota);
  const [menuIds, setMenuIds] = useState<string[]>([]);
  // Per-area "show unauthorized menus (apply)" toggles, split from the legacy
  // single flag so workbench and admin can be configured independently.
  const [workbenchApprovalMode, setWorkbenchApprovalMode] = useState(false);
  const [adminApprovalMode, setAdminApprovalMode] = useState(false);
  const [isMenuLoading, setIsMenuLoading] = useState(false);
  const [menuLoadFailed, setMenuLoadFailed] = useState(false);
  const [initialEditSnapshot, setInitialEditSnapshot] = useState("");
  const [isSaving, setIsSaving] = useState(false);

  const defaultMenuIds = useMemo(() => [...DEFAULT_ENABLED_MENU_IDS], []);

  const roleTableCols = useMemo(
    () => [
      { defaultWidth: 148, minWidth: 112 },
      { defaultWidth: 166, minWidth: 120 },
      { defaultWidth: 100, minWidth: 80 },
      { defaultWidth: 96, minWidth: 78 },
      { defaultWidth: 112, minWidth: 88 },
      { defaultWidth: 80, minWidth: 72 },
      { defaultWidth: 108, minWidth: 90 },
      { defaultWidth: 152, minWidth: 142 },
      { defaultWidth: 152, minWidth: 142 },
      { defaultWidth: 124, minWidth: 112 },
    ],
    [],
  );
  const rc = useResizableColumns(roleTableCols);
  /** 最后一列（操作）不显示列宽拖拽把手，见 ColumnResizeHandle */
  const roleLastResizeColIndex = roleTableCols.length - 2;

  /**
   * Dirty-check snapshot. Takes an options object on purpose: the previous
   * eleven positional booleans/strings alternated types, so a mis-ordered call
   * type-checked fine and silently broke the unsaved-changes prompt.
   */
  const buildEditSnapshot = (input: {
    roleName: string;
    roleType: string;
    departmentId: string;
    quota: RoleQuotaState;
    menuIds: string[];
    workbenchApprovalMode: boolean;
    adminApprovalMode: boolean;
  }) =>
    JSON.stringify({
      roleName: input.roleName,
      roleType: input.roleType,
      departmentId: input.departmentId,
      quota: serializeRoleQuotaSnapshot(input.quota),
      menuIds: [...input.menuIds].sort(),
      workbenchApprovalMode: input.workbenchApprovalMode,
      adminApprovalMode: input.adminApprovalMode,
    });

  const loadDepartments = async () => {
    // F038: only the root layer is needed here (default role-scope selection);
    // the scope picker itself lazy-loads. Avoids fetching the whole org tree.
    const res = await getDepartmentChildrenApi(null);
    if (res) setDeptTree(res);
  };

  const loadRoles = async (nextPage = page, nextKeyword = keyword) => {
    const res = await getRolesPageApi({ page: nextPage, limit: 20, keyword: nextKeyword || undefined });
    if (res) {
      setRoles(res.data || []);
      setTotal(res.total || 0);
    }
  };

  useEffect(() => {
    void loadDepartments().catch(showApiError);
  }, []);

  useEffect(() => {
    void loadRoles(1, keyword).catch(showApiError);
    setPage(1);
  }, [keyword]);

  const fmtTime = (v?: string) => (v ? String(v).replace("T", " ").slice(0, 19) : "-");

  const openCreate = () => {
    const nextDepartmentId = isPlatformAdmin ? "none" : deptTree[0] ? String(deptTree[0].id) : "none";
    const nextMenuIds = [...defaultMenuIds];
    setActiveRole(null);
    setRoleName("");
    setRoleType("tenant");
    setDepartmentId(nextDepartmentId);
    const nextQuota = createDefaultRoleQuota();
    setQuota(nextQuota);
    setWorkbenchApprovalMode(false);
    setAdminApprovalMode(false);
    setMenuIds(nextMenuIds);
    setIsMenuLoading(false);
    setMenuLoadFailed(false);
    setInitialEditSnapshot(
      buildEditSnapshot({
        roleName: "",
        roleType: "tenant",
        departmentId: nextDepartmentId,
        quota: nextQuota,
        menuIds: nextMenuIds,
        workbenchApprovalMode: false,
        adminApprovalMode: false,
      }),
    );
    setEditOpen(true);
  };

  const loadRoleMenus = async (role: ROLE, roleQuota: RoleQuotaState) => {
    setIsMenuLoading(true);
    setMenuLoadFailed(false);
    try {
    const menuRes = await getRoleMenuV2Api(role.id);
    if (!Array.isArray(menuRes)) {
      setMenuLoadFailed(true);
      setInitialEditSnapshot("");
      setIsMenuLoading(false);
      return;
    }
    const ids = normalizeRoleMenuSelection(menuRes);
    setMenuIds(ids);
    const qc = (role.quota_config || {}) as Record<string, unknown>;
    // Scoped keys supersede the legacy global flag; fall back to it for roles
    // saved before the split so the dialog mirrors the current behavior.
    const legacyApproval = Boolean(qc.menu_approval_mode);
    const workbenchApproval = Boolean(qc.menu_approval_mode_workbench ?? legacyApproval);
    const adminApproval = Boolean(qc.menu_approval_mode_admin ?? legacyApproval);
    setWorkbenchApprovalMode(workbenchApproval);
    setAdminApprovalMode(adminApproval);
    setInitialEditSnapshot(
      buildEditSnapshot({
        roleName: role.role_name || "",
        roleType: role.role_type || "tenant",
        departmentId: role.department_id ? String(role.department_id) : "none",
        quota: roleQuota,
        menuIds: ids,
        workbenchApprovalMode: workbenchApproval,
        adminApprovalMode: adminApproval,
      }),
    );
    setIsMenuLoading(false);
    } catch (error) {
      setMenuLoadFailed(true);
      setInitialEditSnapshot("");
      showApiError(error);
    } finally {
      setIsMenuLoading(false);
    }
  };

  const openEdit = async (role: ROLE) => {
    setActiveRole(role);
    setRoleName(role.role_name || "");
    setRoleType(role.role_type === "global" ? "global" : "tenant");
    setDepartmentId(role.department_id ? String(role.department_id) : "none");
    const roleQuota = parseRoleQuota(role.quota_config);
    setQuota(roleQuota);
    setMenuIds([]);
    setMenuLoadFailed(false);
    setEditOpen(true);
    await loadRoleMenus(role, roleQuota);
  };

  const buildQuotaConfig = (): Record<string, unknown> => {
    const base = buildRoleQuotaConfig(
      quota,
      activeRole?.quota_config ? { ...(activeRole.quota_config as Record<string, unknown>) } : {},
    );
    base.menu_approval_mode_workbench = workbenchApprovalMode;
    base.menu_approval_mode_admin = adminApprovalMode;
    // Keep the legacy global flag in sync (= OR of both scopes) for any
    // consumer that still reads it during the transition.
    base.menu_approval_mode = workbenchApprovalMode || adminApprovalMode;
    return base;
  };

  const submitRole = async () => {
    if (isSaving || !roleName.trim() || roleName.length > 128 || isMenuLoading || menuLoadFailed) return;
    const quotaError = validateRoleQuota(quota);
    if (quotaError) {
      toast.show({ type: "error", message: String(t(quotaError) ?? '') });
      return;
    }
    setIsSaving(true);
    const quota_config = buildQuotaConfig();
    // Build the payload only from the current UI selection. API-only legacy or
    // unknown values must not survive an edit just because they were loaded.
    const selectedMenuIds = normalizeRoleMenuSelection(menuIds);
    const payload = {
      role_name: roleName.trim(),
      department_id: departmentId === "none" ? null : Number(departmentId),
      quota_config,
      remark: "PRD 2.5 role",
      menu_ids: selectedMenuIds,
    };
    try {
      if (!activeRole) {
        await createRoleV2Api({ ...payload, role_type: roleType });
      } else {
        await updateRoleV2Api(activeRole.id, payload);
      }

      toast.show({ type: "success", message: String(t("saved") ?? '') });
      setEditOpen(false);
      await loadRoles();
    } catch (error) {
      showApiError(error);
    } finally {
      setIsSaving(false);
    }
  };

  const onDelete = (item: ROLE) => {
    const description = t("system.roleDeleteDescription");
    bsConfirm({
      title: t("system.roleDeleteTitle", { name: item.role_name }),
      desc: item.role_type === "global" ? (
        <>
          <span className="mb-2 block">{t("system.roleDeleteSharedScope")}</span>
          <span className="block">{description}</span>
        </>
      ) : description,
      canelTxt: t("system.deleteConfirmation.cancel"),
      okTxt: t("system.deleteConfirmation.confirm"),
      onOk: async (next) => {
          await deleteRoleV2Api(item.id);
          await loadRoles();
          toast.show({ type: "success", message: String(t("deleteSuccess") ?? '') });
          next();
      },
    });
  };

  const isMenuEnabled = (id: string) => menuIds.includes(id);

  /** 一级开关：开启只增父级；关闭时联动移除其下所有二级（含任务模式等挂在子项下的
   *  嵌套依赖），与保存时的依赖清理一致——避免父级关了二级还残留勾选状态。 */
  const toggleMenuGroup = (parentId: string, children: readonly string[], checked: boolean) => {
    setMenuIds((prev) => {
      const next = new Set(prev);
      if (checked) {
        next.add(parentId);
      } else {
        next.delete(parentId);
        children.forEach((child) => {
          next.delete(child);
          const deps = CHILD_DEPENDENTS[child] || [];
          deps.forEach((dep) => next.delete(dep));
        });
      }
      return Array.from(next);
    });
  };

  const toggleMenuItem = (_parentId: string, _children: readonly string[], id: string, checked: boolean) => {
    setMenuIds((prev) => {
      const next = new Set(prev);
      if (checked) {
        next.add(id);
      } else {
        next.delete(id);
        const dependents = CHILD_DEPENDENTS[id] || [];
        dependents.forEach((dep) => next.delete(dep));
      }
      return Array.from(next);
    });
  };

  const scopeLabel = (el: ROLE) => {
    // 作用域以 department_id 为准；全路径优先用后端按 path 解析的字段（不受部门树裁剪影响）
    if (!el.department_id) return t("system.scopeAllDepartments");
    const fromApi = (el.department_scope_path || "").trim();
    if (fromApi) return fromApi;
    // F038: no full tree on hand for an ancestor-path lookup; fall back to the
    // role's own department_name. The backend department_scope_path above is the
    // authoritative full-path source and is unaffected.
    return el.department_name || "-";
  };

  const creatorLabel = (el: ROLE) => {
    return el.creator_name?.trim() || "-";
  };

  const formatKnowledgeSpaceUploadQuota = (el: ROLE) =>
    formatRoleQuotaGb((el.quota_config || {}).knowledge_space_file, t("system.unlimited"));

  const formatChannelCreationLimit = (el: ROLE) =>
    formatRoleQuotaCount((el.quota_config || {}).channel, ROLE_QUOTA_DEFAULT_CHANNEL, t("system.unlimited"));

  const formatSpaceCreationLimit = (el: ROLE) =>
    formatRoleQuotaCount(
      (el.quota_config || {}).knowledge_space,
      ROLE_QUOTA_DEFAULT_SPACE_CREATE,
      t("system.unlimited"),
    );

  const hasUnsavedEditChanges = useMemo(() => {
    if (!editOpen || !initialEditSnapshot) return false;
    const current = buildEditSnapshot({
      roleName,
      roleType,
      departmentId,
      quota,
      menuIds,
      workbenchApprovalMode,
      adminApprovalMode,
    });
    return current !== initialEditSnapshot;
  }, [editOpen, initialEditSnapshot, roleName, roleType, departmentId, quota, menuIds, workbenchApprovalMode, adminApprovalMode]);

  const requestCloseEditDialog = () => {
    if (!hasUnsavedEditChanges) {
      setEditOpen(false);
      return;
    }
    bsConfirm({
      title: t("prompt"),
      desc: t("flow.unsavedChangesConfirmation"),
      okTxt: t("flow.leave"),
      canelTxt: t("cancel"),
      onOk: (next) => {
        setEditOpen(false);
        next();
      },
    });
  };

  return {
    requestCloseEditDialog,
    t,
    setKeyword,
    openCreate,
    rc,
    roleLastResizeColIndex,
    roles,
    scopeLabel,
    formatKnowledgeSpaceUploadQuota,
    formatChannelCreationLimit,
    formatSpaceCreationLimit,
    creatorLabel,
    fmtTime,
    openEdit,
    onDelete,
    page,
    total,
    setPage,
    loadRoles,
    keyword,
    editOpen,
    setEditOpen,
    activeRole,
    roleName,
    setRoleName,
    roleType,
    setRoleType,
    departmentId,
    setDepartmentId,
    isPlatformAdmin,
    quota,
    setQuota,
    isMenuLoading,
    menuLoadFailed,
    loadRoleMenus,
    workbenchApprovalMode,
    setWorkbenchApprovalMode,
    toggleMenuGroup,
    isMenuEnabled,
    toggleMenuItem,
    adminApprovalMode,
    setAdminApprovalMode,
    isSaving,
    submitRole,
  };
}
interface RolesProps {
  headerTarget?: HTMLDivElement | null;
}

export default function Roles({ headerTarget }: RolesProps) {
  return <RolesView controller={useRolesController()} headerTarget={headerTarget} />;
}
