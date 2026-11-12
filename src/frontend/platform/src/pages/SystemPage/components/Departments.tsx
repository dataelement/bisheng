import { useCallback, useContext, useEffect, useRef, useState } from "react";
import { Button, Checkbox, Tag, toast } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { useTranslation } from "react-i18next";
import { departmentDisplayName } from "@/components/bs-comp/department/departmentDisplayName";
import {
  LazyDepartmentTree,
  useLazyDepartmentTree,
} from "@/components/bs-comp/department";
import { locationContext } from "@/contexts/locationContext";
import { userContext } from "@/contexts/userContext";
import { getDepartmentChildrenApi } from "@/controllers/API/department";
import {
  locateOrganizationMemberApi,
  type OrganizationDepartmentResult,
  type OrganizationMemberResult,
} from "@/controllers/API/organization";
import { showApiError } from "@/controllers/request";
import { CreateDepartmentDialog } from "@/pages/DepartmentPage/components/CreateDepartmentDialog";
import { DepartmentSettingsDialog } from "@/pages/DepartmentPage/components/DepartmentSettingsDialog";
import {
  MemberTable,
  type MemberLocationRequest,
} from "@/pages/DepartmentPage/components/MemberTable";
import { MountTenantDialog } from "@/pages/DepartmentPage/components/MountTenantDialog";
import { OrganizationSearchPanel } from "@/pages/DepartmentPage/components/OrganizationSearchPanel";
import type { DepartmentTreeNode } from "@/types/api/department";

export default function Departments() {
  const { t } = useTranslation();
  const { appConfig } = useContext(locationContext);
  const { user } = useContext(userContext);
  const [includeArchived, setIncludeArchived] = useState(false);
  const tree = useLazyDepartmentTree({
    includeArchived,
    autoExpandRoots: true,
  });
  const treeRef = useRef(tree);
  treeRef.current = tree;
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const selectedIdRef = useRef(selectedId);
  selectedIdRef.current = selectedId;
  const [selectedSnapshot, setSelectedSnapshot] =
    useState<DepartmentTreeNode | null>(null);
  const selectedDept =
    (selectedId == null ? null : tree.getNode(selectedId)) ?? selectedSnapshot;
  const [createOpen, setCreateOpen] = useState(false);
  const [createParentId, setCreateParentId] = useState<number | null>(null);
  const [settingsTarget, setSettingsTarget] =
    useState<DepartmentTreeNode | null>(null);
  const [mountTarget, setMountTarget] = useState<{
    id: number;
    name: string;
  } | null>(null);
  const [membersRefreshSignal, setMembersRefreshSignal] = useState(0);
  const [memberFilter, setMemberFilter] = useState("all");
  const [memberLocation, setMemberLocation] = useState<MemberLocationRequest>();
  const locateSequence = useRef(0);
  const rowRefs = useRef(new Map<string, HTMLDivElement>());
  const [leftPaneWidth, setLeftPaneWidth] = useState(260);
  const isResizingRef = useRef(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const selectNode = useCallback((node: DepartmentTreeNode) => {
    setSelectedId(node.id);
    selectedIdRef.current = node.id;
    setSelectedSnapshot(node);
    setMemberLocation(undefined);
  }, []);

  useEffect(() => {
    if (selectedId == null && tree.rootIds.length > 0) {
      const first = tree.getNode(tree.rootIds[0]);
      if (first) selectNode(first);
    }
  }, [tree, selectedId, selectNode]);

  const handleCreateClick = (parentId: number | null = null) => {
    setCreateParentId(parentId);
    setCreateOpen(true);
  };
  const handleTreeChange = useCallback(
    async (removedDeptId?: string) => {
      await tree.refreshAll();
      setMembersRefreshSignal((value) => value + 1);
      if (selectedIdRef.current !== selectedDept?.id) return;
      if (removedDeptId && selectedDept?.dept_id === removedDeptId) {
        const parent =
          selectedDept.parent_id == null
            ? undefined
            : tree.getNode(selectedDept.parent_id);
        if (parent && (includeArchived || parent.status !== "archived"))
          selectNode(parent);
        else {
          const roots = await getDepartmentChildrenApi(null, includeArchived);
          const root = roots.find((node) => node.dept_id !== removedDeptId);
          if (root) selectNode(root);
          else {
            setSelectedId(null);
            setSelectedSnapshot(null);
          }
        }
      } else if (!removedDeptId && selectedDept) {
        await treeRef.current.reveal(selectedDept.id);
        window.requestAnimationFrame(() => {
          if (selectedIdRef.current === selectedDept.id)
            rowRefs.current
              .get(selectedDept.dept_id)
              ?.scrollIntoView({ block: "nearest", behavior: "smooth" });
        });
      }
    },
    [tree, selectedDept, includeArchived, selectNode]
  );

  const scrollTreeTo = (deptId: string) => {
    window.requestAnimationFrame(() =>
      window.requestAnimationFrame(() => {
        rowRefs.current
          .get(deptId)
          ?.scrollIntoView({ block: "nearest", behavior: "smooth" });
      })
    );
  };
  const revealDepartment = async (id: number) => {
    const chain = await tree.reveal(id);
    await new Promise<void>((resolve) =>
      window.requestAnimationFrame(() => resolve())
    );
    // Reveal can load a new branch; read the controller from the latest render.
    const currentTree = treeRef.current;
    const node = currentTree.getNode(id);
    if (!chain.length || !node)
      throw new Error(t("bs:organization.locationChanged"));
    if (node.has_children && !currentTree.expanded.has(node.id))
      currentTree.toggle(node);
    return node;
  };
  const handleSelectDepartment = async (
    result: OrganizationDepartmentResult
  ) => {
    const node = await revealDepartment(result.id);
    selectNode(node);
    setMemberLocation({
      userId: null,
      deptId: node.dept_id,
      page: 1,
      requestId: ++locateSequence.current,
    });
    scrollTreeTo(node.dept_id);
  };
  const handleSelectMember = async (result: OrganizationMemberResult) => {
    const [node, location] = await Promise.all([
      revealDepartment(result.department.id),
      locateOrganizationMemberApi(
        result.department.dept_id,
        result.user_id,
        memberFilter,
        includeArchived
      ),
    ]);
    selectNode(node);
    setMemberFilter(
      location.is_primary_filter == null
        ? "all"
        : String(location.is_primary_filter)
    );
    setMemberLocation({
      userId: result.user_id,
      deptId: node.dept_id,
      page: location.page,
      requestId: ++locateSequence.current,
    });
    if (location.filter_adjusted)
      toast.show({
        type: "info",
        message: t("bs:organization.filterAdjusted"),
      });
    scrollTreeTo(node.dept_id);
  };

  useEffect(() => {
    const handleMove = (event: MouseEvent) => {
      if (!isResizingRef.current || !containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      setLeftPaneWidth(
        Math.max(
          240,
          Math.min(
            Math.min(520, Math.max(240, rect.width - 360)),
            event.clientX - rect.left
          )
        )
      );
    };
    const handleStop = () => {
      isResizingRef.current = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    window.addEventListener("mousemove", handleMove);
    window.addEventListener("mouseup", handleStop);
    return () => {
      window.removeEventListener("mousemove", handleMove);
      window.removeEventListener("mouseup", handleStop);
      handleStop();
    };
  }, []);

  return (
    <div
      ref={containerRef}
      className="flex h-[calc(100vh-140px-var(--license-banner-h,0px))] min-h-[360px]"
    >
      <div
        className="flex min-w-[240px] flex-col border-r pr-4 pt-2"
        style={{ width: leftPaneWidth }}
      >
        <div className="mb-4 flex items-center justify-between gap-2">
          <h2 className="shrink-0 text-sm font-semibold">
            {t("bs:department.tree")}
          </h2>
          <label className="ml-auto flex cursor-pointer items-center gap-1.5 whitespace-nowrap text-xs text-muted-foreground">
            <Checkbox
              checked={includeArchived}
              onCheckedChange={(checked) => {
                const include = checked === true;
                if (!include && selectedDept?.status === "archived") {
                  let parent =
                    selectedDept.parent_id == null
                      ? undefined
                      : tree.getNode(selectedDept.parent_id);
                  while (parent?.status === "archived")
                    parent =
                      parent.parent_id == null
                        ? undefined
                        : tree.getNode(parent.parent_id);
                  if (parent) selectNode(parent);
                  else {
                    setSelectedId(null);
                    setSelectedSnapshot(null);
                  }
                }
                setIncludeArchived(include);
              }}
            />
            {t("bs:organization.showArchived")}
          </label>
          <Button
            size="small"
            variant="text"
            aria-label={t("bs:department.create")}
            title={t("bs:department.create")}
            onClick={() => handleCreateClick()}
          >
            <Outlined.Plus className="size-4" />
          </Button>
        </div>
        <OrganizationSearchPanel
          includeArchived={includeArchived}
          preferredDepartmentId={selectedDept?.id}
          onSelectDepartment={handleSelectDepartment}
          onSelectMember={handleSelectMember}
        >
          <LazyDepartmentTree
            controller={tree}
            showSearch={false}
            selectedDeptId={selectedDept?.dept_id}
            onSelect={selectNode}
            renderRowSuffix={(node) => (
              <>
                {node.is_tenant_root && (
                  <Tag size="small" color="brand" className="mr-1 shrink-0">
                    {t("bs:tenant.mountedTag")}
                  </Tag>
                )}
                {node.status !== "archived" && (
                  <Button
                    size="small"
                    variant="text"
                    className="invisible shrink-0 group-hover:visible"
                    aria-label={t("bs:department.create")}
                    onClick={(event) => {
                      event.stopPropagation();
                      handleCreateClick(node.id);
                    }}
                  >
                    <Outlined.Plus className="size-3.5" />
                  </Button>
                )}
              </>
            )}
            rowRef={(deptId, element) => {
              if (element) rowRefs.current.set(deptId, element);
              else rowRefs.current.delete(deptId);
            }}
          />
        </OrganizationSearchPanel>
      </div>
      <div
        role="separator"
        aria-orientation="vertical"
        className="w-1 shrink-0 cursor-col-resize hover:bg-border"
        onMouseDown={() => {
          isResizingRef.current = true;
          document.body.style.cursor = "col-resize";
          document.body.style.userSelect = "none";
        }}
      />
      <div className="min-w-0 flex-1 overflow-auto pl-4 pt-2">
        {selectedDept ? (
          <MemberTable
            deptId={selectedDept.dept_id}
            deptName={departmentDisplayName(
              selectedDept,
              t("bs:department.defaultOrganization")
            )}
            dept={selectedDept}
            isArchived={selectedDept.status === "archived"}
            onChanged={(removedDeptId?: string) =>
              void handleTreeChange(removedDeptId).catch(showApiError)
            }
            membersRefreshSignal={membersRefreshSignal}
            location={memberLocation}
            isPrimaryFilter={memberFilter}
            onFilterChange={(value) => {
              setMemberLocation(undefined);
              setMemberFilter(value);
            }}
            toolbarActions={
              <>
                <Button
                  variant="outlined"
                  color="default"
                  onClick={() => setSettingsTarget(selectedDept)}
                >
                  {t("bs:department.settings")}
                </Button>
                <Button
                  variant="outlined"
                  disabled={selectedDept.status === "archived"}
                  onClick={() => handleCreateClick(selectedDept.id)}
                >
                  {t("bs:department.create")}
                </Button>
              </>
            }
          />
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            {t("bs:department.selectDept")}
          </div>
        )}
      </div>
      {createOpen && (
        <CreateDepartmentDialog
          defaultParentId={createParentId}
          onClose={() => setCreateOpen(false)}
          onCreated={() => {
            setCreateOpen(false);
            void tree.reloadLayer(createParentId).catch(showApiError);
          }}
        />
      )}
      {settingsTarget && (
        <DepartmentSettingsDialog
          dept={settingsTarget}
          showTrafficControl={user?.role === "admin" && !!appConfig.isPro}
          onClose={() => setSettingsTarget(null)}
          onChanged={(removed) => {
            setSettingsTarget(null);
            void handleTreeChange(removed).catch(showApiError);
          }}
          onMarkAsTenant={
            appConfig.multiTenantEnabled && user?.is_global_super
              ? (id, name) => setMountTarget({ id, name })
              : undefined
          }
        />
      )}
      {mountTarget && (
        <MountTenantDialog
          deptId={mountTarget.id}
          deptName={mountTarget.name}
          onClose={() => setMountTarget(null)}
          onMounted={() => {
            setMountTarget(null);
            void handleTreeChange().catch(showApiError);
          }}
        />
      )}
    </div>
  );
}
