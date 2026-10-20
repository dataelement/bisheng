// @ts-strict-ignore
import { notification } from '@bisheng/ui';
import { MemberTableView } from "./MemberTableView";

import { useResizableColumns } from "@/components/bs-ui/table/useResizableColumns";

import { userContext } from "@/contexts/userContext";
import {
  getDepartmentAdminsApi,
  getDepartmentMembersApi,
  getDepartmentPathTreeApi,
  searchGlobalMembersApi,
  type GlobalMemberSearchRow,
} from "@/controllers/API/department";
import { disableUserApi } from "@/controllers/API/user";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import type {
  DepartmentAdmin,
  DepartmentMember,
  DepartmentSearchResult,
  DepartmentTreeNode,
} from "@/types/api/department";
import { buildMemberDisplayNameMap } from "@/utils/userDisplayName";

import { useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

interface MemberTableProps {
  deptId: string;
  deptName: string;
  dept?: DepartmentTreeNode | null;
  isArchived?: boolean;
  onChanged: () => void;
  /** 父级在部门设置等变更后递增，用于在不切换部门时强制重新拉取成员（如部门管理员 FGA 更新后刷新「角色」列） */
  membersRefreshSignal?: number;
  /** 全组织搜索定位后高亮该用户行 */
  highlightUserId?: number | null;
  onHighlightConsumed?: () => void;
  /** 点击全组织搜索结果时，通知父级切换部门并滚动左侧树 */
  onRequestLocateMember?: (payload: { primaryDeptDeptId: string; userId: number }) => void;
}

export function useMemberTableController({
  deptId,
  deptName,
  dept = null,
  isArchived = false,
  onChanged,
  membersRefreshSignal = 0,
  highlightUserId = null,
  onHighlightConsumed,
  onRequestLocateMember,
}: MemberTableProps) {
  const { t } = useTranslation();
  const { user } = useContext(userContext);
  const userPwdModalRef = useRef<{ open: (userId: string | number) => void } | null>(null);
  const [members, setMembers] = useState<DepartmentMember[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [keyword, setKeyword] = useState("");
  const [isPrimaryFilter, setIsPrimaryFilter] = useState<string>("all");
  const [addOpen, setAddOpen] = useState(false);
  const [editMember, setEditMember] = useState<DepartmentMember | null>(null);
  const [memberScope, setMemberScope] = useState<"dept" | "org">("dept");
  const [globalRows, setGlobalRows] = useState<GlobalMemberSearchRow[]>([]);
  const [globalTotal, setGlobalTotal] = useState(0);
  const [globalPage, setGlobalPage] = useState(1);
  const [globalLoading, setGlobalLoading] = useState(false);
  const [directAdmins, setDirectAdmins] = useState<DepartmentAdmin[]>([]);
  const [inheritedAdmins, setInheritedAdmins] = useState<(DepartmentAdmin & { sourceDeptName: string })[]>([]);
  const pageRef = useRef(page);
  pageRef.current = page;

  useEffect(() => {
    setMemberScope("dept");
    setGlobalPage(1);
    setGlobalRows([]);
    setGlobalTotal(0);
  }, [deptId]);

  const memberDisplayNames = useMemo(() => buildMemberDisplayNameMap(members), [members]);

  // F038: ancestors (for inherited-admin lookup) come from a path-tree fetch
  // instead of walking a full tree that's no longer passed in. The chain is
  // root→self; everything but the leaf is an ancestor (order doesn't matter —
  // loadAdminSummary flattens + dedups).
  const [ancestorDepartments, setAncestorDepartments] = useState<DepartmentTreeNode[]>([]);
  useEffect(() => {
    const internalId = dept?.id;
    if (internalId == null) {
      setAncestorDepartments([]);
      return;
    }
    let cancelled = false;
    captureAndAlertRequestErrorHoc(getDepartmentPathTreeApi(internalId)).then((res) => {
      if (cancelled) return;
      const pruned = (res as DepartmentSearchResult | null) ?? null;
      const chain: DepartmentTreeNode[] = [];
      let cur = pruned?.roots?.[0];
      while (cur) {
        chain.push(cur);
        cur = cur.children?.[0];
      }
      setAncestorDepartments(chain.slice(0, -1));
    });
    return () => {
      cancelled = true;
    };
  }, [dept?.id]);

  const loadAdminSummary = useCallback(() => {
    let cancelled = false;
    const run = async () => {
      const direct = await captureAndAlertRequestErrorHoc(getDepartmentAdminsApi(deptId));
      if (cancelled) return;
      const directRows = Array.isArray(direct) ? direct : [];
      const directUserIds = new Set(directRows.map((a) => Number(a.user_id)));
      const inheritedResults = await Promise.all(
        ancestorDepartments.map(async (ancestor) => {
          try {
            const rows = await getDepartmentAdminsApi(ancestor.dept_id);
            return (rows || []).map((row) => ({
              ...row,
              sourceDeptName: ancestor.name,
            }));
          } catch {
            return [];
          }
        }),
      );
      if (cancelled) return;
      const seenInherited = new Set<number>();
      const inheritedRows = inheritedResults.flat().filter((row) => {
        const uid = Number(row.user_id);
        if (directUserIds.has(uid) || seenInherited.has(uid)) return false;
        seenInherited.add(uid);
        return true;
      });
      setDirectAdmins(directRows);
      setInheritedAdmins(inheritedRows);
    };
    void run();
    return () => {
      cancelled = true;
    };
  }, [ancestorDepartments, deptId]);

  const loadMembers = useCallback(() => {
    if (memberScope !== "dept") return;
    const params: Record<string, string | number> = {
      page: pageRef.current,
      limit: 20,
      keyword,
    };
    if (isPrimaryFilter !== "all") {
      params.is_primary = parseInt(isPrimaryFilter, 10);
    }
    captureAndAlertRequestErrorHoc(getDepartmentMembersApi(deptId, params)).then((res) => {
      if (res) {
        setMembers(res.data);
        setTotal(res.total);
      }
    });
  }, [deptId, keyword, isPrimaryFilter, memberScope]);

  useEffect(() => {
    if (memberScope !== "dept") return;
    setPage(1);
    pageRef.current = 1;
    loadMembers();
  }, [deptId, keyword, isPrimaryFilter, memberScope, loadMembers]);

  useEffect(() => {
    if (membersRefreshSignal === 0) return;
    if (memberScope !== "dept") return;
    loadMembers();
  }, [membersRefreshSignal, loadMembers, memberScope]);

  useEffect(() => loadAdminSummary(), [loadAdminSummary, membersRefreshSignal]);

  const loadGlobalMembers = useCallback(() => {
    const kw = keyword.trim();
    if (!kw) {
      setGlobalRows([]);
      setGlobalTotal(0);
      setGlobalLoading(false);
      return;
    }
    setGlobalLoading(true);
    captureAndAlertRequestErrorHoc(searchGlobalMembersApi({ keyword: kw, page: globalPage, limit: 20 })).then((res) => {
      setGlobalLoading(false);
      if (res) {
        setGlobalRows(res.data);
        setGlobalTotal(res.total);
      }
    });
  }, [keyword, globalPage]);

  useEffect(() => {
    if (memberScope !== "org") return;
    setGlobalPage(1);
  }, [keyword, memberScope]);

  useEffect(() => {
    if (memberScope !== "org") return;
    const t = window.setTimeout(() => void loadGlobalMembers(), 280);
    return () => window.clearTimeout(t);
  }, [memberScope, keyword, globalPage, loadGlobalMembers]);

  useEffect(() => {
    if (memberScope !== "dept" || highlightUserId == null) return;
    const hit = members.some((m) => m.user_id === highlightUserId);
    if (!hit) return;
    const t = window.setTimeout(() => {
      const el = document.querySelector(`[data-member-row="${highlightUserId}"]`);
      el?.scrollIntoView({ block: "nearest", behavior: "smooth" });
      onHighlightConsumed?.();
    }, 120);
    return () => window.clearTimeout(t);
  }, [members, highlightUserId, memberScope, onHighlightConsumed]);

  const handlePageChange = useCallback(
    (p: number) => {
      setPage(p);
      pageRef.current = p;
      loadMembers();
    },
    [loadMembers],
  );

  const handleGlobalPageChange = useCallback((p: number) => {
    setGlobalPage(p);
  }, []);

  const handleToggleEnabled = useCallback(
    (m: DepartmentMember, enabled: boolean) => {
      if (isArchived) return;
      setMembers((list) => list.map((x) => (x.user_id === m.user_id ? { ...x, enabled } : x)));
      captureAndAlertRequestErrorHoc(
        disableUserApi(m.user_id, enabled ? 0 : 1).then(() => {
          notification.open({ type: "success", title: String(t("prompt") ?? ''), description: String(t(enabled ? "bs:department.accountEnabledToast" : "bs:department.accountDisabledToast") ?? '') });
          onChanged();
        }),
      ).then((res) => {
        // HoC returns false on error — revert optimistic toggle by reloading.
        if (res === false) loadMembers();
      });
    },
    [isArchived, loadMembers, onChanged, t],
  );

  const handleAdded = useCallback(() => {
    setAddOpen(false);
    loadMembers();
    onChanged();
  }, [loadMembers, onChanged]);

  const handleEditUser = useCallback(
    (m: DepartmentMember) => {
      if (isArchived) return;
      setEditMember(m);
    },
    [isArchived],
  );

  const handleEditClose = useCallback(() => {
    setEditMember(null);
  }, []);

  const handleEditSaved = useCallback(() => {
    setEditMember(null);
    loadMembers();
    onChanged();
  }, [loadMembers, onChanged]);

  const fmtTime = (v?: string | Date | null) => (v ? String(v).replace("T", " ").slice(0, 19) : "-");

  const memberCols = useMemo(
    () => [
      { defaultWidth: 160, minWidth: 120 },
      { defaultWidth: 120, minWidth: 96 },
      { defaultWidth: 180, minWidth: 120 },
      { defaultWidth: 180, minWidth: 120 },
      { defaultWidth: 160, minWidth: 120 },
      { defaultWidth: 88, minWidth: 72 },
      { defaultWidth: 168, minWidth: 120 },
    ],
    [],
  );
  const mrc = useResizableColumns(memberCols);
  const memberLastCol = memberCols.length - 1;

  return {
    memberLastCol,
    memberScope,
    setMemberScope,
    t,
    keyword,
    setKeyword,
    isPrimaryFilter,
    setIsPrimaryFilter,
    isArchived,
    setAddOpen,
    directAdmins,
    inheritedAdmins,
    globalLoading,
    globalRows,
    onRequestLocateMember,
    globalPage,
    globalTotal,
    handleGlobalPageChange,
    mrc,
    members,
    highlightUserId,
    memberDisplayNames,
    fmtTime,
    user,
    handleToggleEnabled,
    handleEditUser,
    userPwdModalRef,
    page,
    total,
    handlePageChange,
    addOpen,
    deptId,
    deptName,
    handleAdded,
    editMember,
    handleEditClose,
    handleEditSaved,
  };
}
export function MemberTable(props: MemberTableProps) {
  return <MemberTableView controller={useMemberTableController(props)} />;
}
