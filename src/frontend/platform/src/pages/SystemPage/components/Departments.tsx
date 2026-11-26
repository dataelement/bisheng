import { useCallback, useContext, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Button, Checkbox, Tooltip, toast } from "@bisheng/ui";
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
  const queryClient = useQueryClient();
  const [directoryRevision, setDirectoryRevision] = useState(0);
  const handleTenantMounted = () => {
    // Mounting changes the business boundary. Drop both browse caches and all
    // local selection/search state before loading the directory in its new scope.
    queryClient.removeQueries(["dept:false"]);
    queryClient.removeQueries(["dept:true"]);
    setDirectoryRevision((revision) => revision + 1);
  };

  return (
    <DepartmentDirectory
      key={directoryRevision}
      onTenantMounted={handleTenantMounted}
    />
  );
}

interface DepartmentDirectoryProps {
  onTenantMounted: () => void;
}

function DepartmentDirectory({ onTenantMounted }: DepartmentDirectoryProps) {
  const { t } = useTranslation();
  const createDepartmentLabel = t("bs:department.create");
  const createChildDepartmentLabel = t("bs:organization.createChildDepartment");
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
  const createTriggerRef = useRef<HTMLButtonElement | null>(null);
  const [settingsTarget, setSettingsTarget] =
    useState<DepartmentTreeNode | null>(null);
  const [mountTarget, setMountTarget] = useState<{
    id: number;
    name: string;
  } | null>(null);
  const [membersRefreshSignal, setMembersRefreshSignal] = useState(0);
  const [memberFilter, setMemberFilter] = useState("all");
  const [directOnly, setDirectOnly] = useState(false);
  const [memberLocation, setMemberLocation] = useState<MemberLocationRequest>();
  const locateSequence = useRef(0);
  const [treeRevealKey, setTreeRevealKey] = useState(0);
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

  const handleCreateClick = (trigger: HTMLButtonElement, parentId: number | null = null) => {
    createTriggerRef.current = trigger;
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
        if (selectedIdRef.current === selectedDept.id)
          setTreeRevealKey((value) => value + 1);
      }
    },
    [tree, selectedDept, includeArchived, selectNode]
  );

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
    setTreeRevealKey((value) => value + 1);
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
    setTreeRevealKey((value) => value + 1);
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
      className="flex h-full min-h-0 overflow-hidden"
    >
      <div
        className="flex min-h-0 min-w-[240px] shrink-0 flex-col border-r pr-4 pt-4"
        style={{ width: leftPaneWidth }}
      >
        <div className="mb-4 flex items-center justify-between gap-2">
          <h2 className="shrink-0 text-base font-semibold">
            {t("bs:department.tree")}
          </h2>
          <Checkbox
            label={t("bs:organization.showArchived")}
            wrapperClassName="ml-auto whitespace-nowrap"
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
          <Tooltip content={createDepartmentLabel}>
            <Button
              type="button"
              size="small"
              color="primary"
              variant="text"
              iconOnly
              icon={<Outlined.Plus aria-hidden />}
              aria-label={createDepartmentLabel}
              onClick={(event) => handleCreateClick(event.currentTarget)}
            />
          </Tooltip>
        </div>
        <OrganizationSearchPanel
          includeArchived={includeArchived}
          preferredDepartmentId={selectedDept?.id}
          onSelectDepartment={handleSelectDepartment}
          onSelectMember={handleSelectMember}
        >
          <LazyDepartmentTree
            controller={tree}
            variant="navigation"
            showSearch={false}
            revealKey={treeRevealKey}
            selectedDeptId={selectedDept?.dept_id}
            onSelect={selectNode}
            renderRowSuffix={(node) => node.status !== "archived" && (
              <Tooltip content={createChildDepartmentLabel}>
                <Button
                  type="button"
                  size="small"
                  color="default"
                  variant="text"
                  iconOnly
                  icon={<Outlined.Plus aria-hidden />}
                  className="size-[var(--tree-slot)] rounded-md [opacity:var(--tree-menu-visibility)] hover:bg-fill-3 [&_svg]:size-4"
                  aria-label={t("bs:organization.createChildDepartmentFor", {
                    name: departmentDisplayName(node, t("bs:department.defaultOrganization")),
                  })}
                  aria-haspopup="dialog"
                  onClick={(event) => handleCreateClick(event.currentTarget, node.id)}
                />
              </Tooltip>
            )}
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
      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden pb-2 pl-4 pt-4">
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
            directOnly={directOnly}
            includeArchived={includeArchived}
            onDirectOnlyChange={(checked) => {
              setMemberLocation(undefined);
              setDirectOnly(checked);
            }}
            isPrimaryFilter={memberFilter}
            onFilterChange={(value) => {
              setMemberLocation(undefined);
              setMemberFilter(value);
            }}
            toolbarActions={
              <Button
                variant="outlined"
                color="default"
                onClick={() => setSettingsTarget(selectedDept)}
              >
                {t("bs:department.settings")}
              </Button>
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
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            createTriggerRef.current?.focus();
          }}
          onCreated={(departmentId) => {
            setCreateOpen(false);
            void tree.reveal(departmentId, { refresh: true }).catch(showApiError);
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
          onMounted={onTenantMounted}
        />
      )}
    </div>
  );
}
