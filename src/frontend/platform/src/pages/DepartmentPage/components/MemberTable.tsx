import { notification } from "@bisheng/ui";
import {
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";
import { useResizableColumns } from "@/components/bs-ui/table/useResizableColumns";
import { userContext } from "@/contexts/userContext";
import {
  getDepartmentAdminsApi,
  getDepartmentMembersApi,
  getDepartmentPathTreeApi,
} from "@/controllers/API/department";
import { disableUserApi } from "@/controllers/API/user";
import { showApiError } from "@/controllers/request";
import type {
  DepartmentAdmin,
  DepartmentMember,
  DepartmentTreeNode,
} from "@/types/api/department";
import { buildMemberDisplayNameMap } from "@/utils/userDisplayName";
import { MemberTableView } from "./MemberTableView";

export interface MemberLocationRequest {
  userId: number | null;
  deptId: string;
  page: number;
  requestId: number;
}

interface MemberTableProps {
  deptId: string;
  deptName: string;
  dept: DepartmentTreeNode;
  isArchived?: boolean;
  onChanged: () => void;
  membersRefreshSignal?: number;
  location?: MemberLocationRequest;
  directOnly?: boolean;
  includeArchived?: boolean;
  onDirectOnlyChange?: (checked: boolean) => void;
  isPrimaryFilter: string;
  onFilterChange: (value: string) => void;
  toolbarActions?: ReactNode;
}

export function useMemberTableController({
  deptId,
  deptName,
  dept,
  isArchived = false,
  onChanged,
  membersRefreshSignal = 0,
  location,
  directOnly = true,
  includeArchived = false,
  onDirectOnlyChange,
  isPrimaryFilter,
  onFilterChange,
  toolbarActions,
}: MemberTableProps) {
  const { t } = useTranslation();
  const { user } = useContext(userContext);
  const userPwdModalRef = useRef<{
    open: (userId: string | number) => void;
  } | null>(null);
  const [members, setMembers] = useState<DepartmentMember[]>([]);
  const [total, setTotal] = useState(0);
  const [directTotal, setDirectTotal] = useState(0);
  const [page, setPage] = useState(1);
  const pageRef = useRef(1);
  const requestRef = useRef<object | null>(null);
  const [loading, setLoading] = useState(false);
  const [memberSearch, setMemberSearch] = useState('');
  const memberKeywordRef = useRef('');
  const searchDepartmentRef = useRef(deptId);
  const [highlightUserId, setHighlightUserId] = useState<number | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [editMember, setEditMember] = useState<DepartmentMember | null>(null);
  const [directAdmins, setDirectAdmins] = useState<DepartmentAdmin[]>([]);
  const [inheritedAdmins, setInheritedAdmins] = useState<
    (DepartmentAdmin & { sourceDeptName: string })[]
  >([]);
  const memberDisplayNames = useMemo(
    () => buildMemberDisplayNameMap(members),
    [members]
  );
  const showArchivedDescendants = !directOnly && includeArchived;

  const loadMembers = useCallback(
    async (requestedPage = pageRef.current) => {
      const requestId = {};
      requestRef.current = requestId;
      setLoading(true);
      try {
        const result = await getDepartmentMembersApi(deptId, {
          page: requestedPage,
          limit: 20,
          ...(memberKeywordRef.current ? { keyword: memberKeywordRef.current } : {}),
          is_primary:
            isPrimaryFilter === "all" ? undefined : Number(isPrimaryFilter),
          ...(!directOnly && {
            include_descendants: true,
            include_archived: showArchivedDescendants,
          }),
        });
        if (requestId !== requestRef.current) return;
        setMembers(result.data);
        setTotal(result.total);
        setDirectTotal(result.direct_total ?? result.total);
      } finally {
        if (requestId === requestRef.current) setLoading(false);
      }
    },
    [deptId, isPrimaryFilter, directOnly, showArchivedDescendants]
  );

  useEffect(() => {
    if (searchDepartmentRef.current !== deptId) {
      searchDepartmentRef.current = deptId;
      memberKeywordRef.current = '';
      setMemberSearch('');
    }
    const freshLocation = location?.deptId === deptId && !memberKeywordRef.current;
    const nextPage = freshLocation && location ? location.page : 1;
    setHighlightUserId(freshLocation && location ? location.userId : null);
    setMembers([]);
    setPage(nextPage);
    pageRef.current = nextPage;
    void loadMembers(nextPage).catch(showApiError);
    return () => {
      requestRef.current = null;
    };
  }, [deptId, isPrimaryFilter, location, loadMembers]);

  const handleMemberSearch = (value: string) => {
    memberKeywordRef.current = value;
    setMemberSearch(value);
    setPage(1);
    pageRef.current = 1;
    setHighlightUserId(null);
    void loadMembers(1).catch(showApiError);
  };

  useEffect(() => {
    if (membersRefreshSignal) void loadMembers().catch(showApiError);
  }, [membersRefreshSignal, loadMembers]);

  useEffect(() => {
    let cancelled = false;
    setDirectAdmins([]);
    setInheritedAdmins([]);
    const load = async () => {
      const [direct, path] = await Promise.all([
        getDepartmentAdminsApi(deptId),
        getDepartmentPathTreeApi(dept.id, isArchived),
      ]);
      const ancestors: DepartmentTreeNode[] = [];
      let node: DepartmentTreeNode | undefined = path.roots[0];
      while (node && node.id !== dept.id) {
        ancestors.push(node);
        node = node.children[0];
      }
      const inherited = await Promise.all(
        ancestors.map(async (ancestor) =>
          (await getDepartmentAdminsApi(ancestor.dept_id)).map((admin) => ({
            ...admin,
            sourceDeptName: ancestor.name,
          }))
        )
      );
      if (cancelled) return;
      const seen = new Set(direct.map((admin) => admin.user_id));
      setDirectAdmins(direct);
      setInheritedAdmins(
        inherited.flat().filter((admin) => {
          if (seen.has(admin.user_id)) return false;
          seen.add(admin.user_id);
          return true;
        })
      );
    };
    void load().catch((error) => {
      if (!cancelled) showApiError(error);
    });
    return () => {
      cancelled = true;
    };
  }, [dept.id, deptId, isArchived, membersRefreshSignal]);

  useEffect(() => {
    if (
      loading ||
      highlightUserId == null ||
      !members.some(
        (member) =>
          member.user_id === highlightUserId &&
          (member.department_id ?? dept.id) === dept.id
      )
    )
      return;
    const frame = window.requestAnimationFrame(() => {
      document
        .querySelector(
          `[data-member-row="${highlightUserId}"][data-member-department="${dept.id}"]`
        )
        ?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    });
    const timer = window.setTimeout(() => setHighlightUserId(null), 5000);
    return () => {
      window.cancelAnimationFrame(frame);
      window.clearTimeout(timer);
    };
  }, [dept.id, members, loading, highlightUserId]);

  const handlePageChange = useCallback(
    (nextPage: number) => {
      setHighlightUserId(null);
      setPage(nextPage);
      pageRef.current = nextPage;
      void loadMembers(nextPage).catch(showApiError);
    },
    [loadMembers]
  );

  const handleToggleEnabled = useCallback(
    (member: DepartmentMember, enabled: boolean) => {
      if (isArchived || member.department?.status === "archived") return;
      setMembers((list) =>
        list.map((row) =>
          row.user_id === member.user_id ? { ...row, enabled } : row
        )
      );
      void disableUserApi(member.user_id, enabled ? 0 : 1)
        .then(() => {
          notification.open({
            type: "success",
            title: t("prompt"),
            description: t(
              enabled
                ? "bs:department.accountEnabledToast"
                : "bs:department.accountDisabledToast"
            ),
          });
          onChanged();
        })
        .catch((error) => {
          setMembers((list) =>
            list.map((row) =>
              row.user_id === member.user_id
                ? { ...row, enabled: member.enabled }
                : row
            )
          );
          showApiError(error);
        });
    },
    [isArchived, onChanged, t]
  );

  const handleAdded = () => {
    setAddOpen(false);
    void loadMembers().catch(showApiError);
    onChanged();
  };
  const handleEditUser = (member: DepartmentMember) => {
    if (!isArchived && member.department?.status !== "archived") setEditMember(member);
  };
  const handleEditClose = () => setEditMember(null);
  const handleEditSaved = () => {
    setEditMember(null);
    void loadMembers().catch(showApiError);
    onChanged();
  };
  const fmtTime = (value?: string | Date | null) =>
    value ? String(value).replace("T", " ").slice(0, 19) : "-";
  const memberCols = useMemo(
    () => [
      { defaultWidth: 140, minWidth: 100 },
      { defaultWidth: 200, minWidth: 140 },
      { defaultWidth: 100, minWidth: 88 },
      { defaultWidth: 160, minWidth: 120 },
      { defaultWidth: 140, minWidth: 100 },
      { defaultWidth: 160, minWidth: 120 },
      { defaultWidth: 72, minWidth: 64 },
      { defaultWidth: 144, minWidth: 120 },
    ],
    []
  );
  const mrc = useResizableColumns(memberCols);
  return {
    memberLastCol: memberCols.length - 1,
    t,
    isPrimaryFilter,
    setIsPrimaryFilter: onFilterChange,
    isArchived,
    setAddOpen,
    directAdmins,
    inheritedAdmins,
    mrc,
    members,
    memberSearch,
    setMemberSearch,
    handleMemberSearch,
    loading,
    highlightUserId,
    memberDisplayNames,
    fmtTime,
    user,
    handleToggleEnabled,
    handleEditUser,
    userPwdModalRef,
    page,
    total,
    directTotal,
    directOnly,
    onDirectOnlyChange,
    handlePageChange,
    addOpen,
    deptId,
    departmentId: dept.id,
    deptName,
    handleAdded,
    editMember,
    handleEditClose,
    handleEditSaved,
    toolbarActions,
  };
}

export function MemberTable(props: MemberTableProps) {
  return <MemberTableView controller={useMemberTableController(props)} />;
}
