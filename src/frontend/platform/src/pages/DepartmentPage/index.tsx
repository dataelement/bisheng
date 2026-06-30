import { LazyDepartmentTree, useLazyDepartmentTree } from "@/components/bs-comp/department"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/bs-ui/tabs"
import { getDepartmentApi } from "@/controllers/API/department"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { locationContext } from "@/contexts/locationContext"
import { userContext } from "@/contexts/userContext"
import { DepartmentTreeNode } from "@/types/api/department"
import { Plus } from "lucide-react"
import { useCallback, useContext, useEffect, useRef, useState } from "react"
import { useTranslation } from "react-i18next"
import { CreateDepartmentDialog } from "./components/CreateDepartmentDialog"
import { DepartmentSettings } from "./components/DepartmentSettings"
import { MemberTable } from "./components/MemberTable"
import { MountTenantDialog } from "./components/MountTenantDialog"

export default function DepartmentPage() {
  const { t } = useTranslation()
  const { appConfig } = useContext(locationContext)
  const { user } = useContext(userContext)
  const multiTenantEnabled = !!appConfig?.multiTenantEnabled
  const canMountTenant = multiTenantEnabled && !!user?.is_global_super

  // F038: management nav tree is now lazy (root layer first, children on expand,
  // server-side search/locate). includeArchived: the management tree shows
  // archived nodes (AC-16); autoExpandRoots mirrors the old "first level open".
  const tree = useLazyDepartmentTree({ includeArchived: true, autoExpandRoots: true })

  // Track the selection by internal id and derive the live node from the tree so
  // a rename/move refresh keeps the right panel in sync; keep a snapshot as a
  // fallback for when the node isn't in a currently-loaded layer.
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [selectedSnapshot, setSelectedSnapshot] = useState<DepartmentTreeNode | null>(null)
  const selectedDept = (selectedId != null ? tree.getNode(selectedId) : null) ?? selectedSnapshot
  const selectedDeptId = selectedDept?.dept_id ?? null

  const [createOpen, setCreateOpen] = useState(false)
  const [createParentId, setCreateParentId] = useState<number | null>(null)
  const [mountTarget, setMountTarget] = useState<{ id: number; name: string } | null>(null)
  const [membersRefreshSignal, setMembersRefreshSignal] = useState(0)
  const [memberHighlightUserId, setMemberHighlightUserId] = useState<number | null>(null)
  const rowRefs = useRef<Map<string, HTMLDivElement>>(new Map())

  const selectNode = useCallback((node: DepartmentTreeNode) => {
    setSelectedId(node.id)
    setSelectedSnapshot(node)
  }, [])

  // Auto-select the first visible root once the root layer loads.
  useEffect(() => {
    if (selectedId == null && tree.rootIds.length > 0) {
      const first = tree.getNode(tree.rootIds[0])
      if (first) selectNode(first)
    }
  }, [tree.rootIds, selectedId, tree, selectNode])

  const handleCreateClick = useCallback((parentId?: number) => {
    setCreateParentId(parentId ?? null)
    setCreateOpen(true)
  }, [])

  const handleCreated = useCallback(() => {
    setCreateOpen(false)
    void tree.reloadLayer(createParentId)
  }, [tree, createParentId])

  const handleMarkAsTenant = useCallback((deptId: number, deptName: string) => {
    setMountTarget({ id: deptId, name: deptName })
  }, [])

  const handleMounted = useCallback(() => {
    setMountTarget(null)
    void tree.refreshAll()
  }, [tree])

  // Create / move / archive / restore / rename: refresh affected (loaded) layers
  // — a move touches both old and new parent, so refresh all loaded layers (AC-05).
  const handleTreeChange = useCallback(
    async (removedDeptId?: string) => {
      // Await the refresh first so, when the removed dept was selected, the
      // auto-select effect picks the FRESH first root — not the stale one.
      await tree.refreshAll()
      if (removedDeptId && selectedDeptId === removedDeptId) {
        setSelectedId(null)
        setSelectedSnapshot(null)
      }
    },
    [tree, selectedDeptId]
  )

  const handleDepartmentSettingsChanged = useCallback(
    (removedDeptId?: string) => {
      handleTreeChange(removedDeptId)
      setMembersRefreshSignal((prev) => prev + 1)
    },
    [handleTreeChange]
  )

  const handleLocateMemberFromGlobal = useCallback(
    async ({ primaryDeptDeptId, userId }: { primaryDeptDeptId: string; userId: number }) => {
      setMemberHighlightUserId(userId)
      // The global search row carries the business dept_id; resolve its internal
      // id, then reveal (expand + load) the branch and scroll to it.
      const detail = await captureAndAlertRequestErrorHoc(getDepartmentApi(primaryDeptDeptId))
      if (!detail) return
      await tree.reveal(detail.id)
      const node = tree.getNode(detail.id)
      if (node) selectNode(node)
      window.setTimeout(() => {
        rowRefs.current.get(primaryDeptDeptId)?.scrollIntoView({ block: "nearest", behavior: "smooth" })
      }, 80)
    },
    [tree, selectNode]
  )

  const handleMemberHighlightConsumed = useCallback(() => setMemberHighlightUserId(null), [])

  // Nav-tree row extras: child-tenant mount badge + quick "create child" button.
  const renderRowSuffix = useCallback(
    (node: DepartmentTreeNode) => (
      <>
        {node.is_tenant_root && (
          <span
            className="mr-1 rounded bg-primary/10 px-1 py-0.5 text-[10px] font-medium text-primary"
            title={t("bs:tenant.mountedBadge", { defaultValue: "子租户挂载点" })}
          >
            {t("bs:tenant.mountedTag", { defaultValue: "子租户" })}
          </span>
        )}
        {node.status !== "archived" && (
          <button
            className="hidden h-5 w-5 shrink-0 items-center justify-center rounded hover:bg-gray-200 group-hover:flex"
            onClick={(e) => {
              e.stopPropagation()
              handleCreateClick(node.id)
            }}
            title={t("bs:department.create")}
          >
            <Plus className="h-3.5 w-3.5" />
          </button>
        )}
      </>
    ),
    [handleCreateClick, t]
  )

  return (
    <div className="flex h-full w-full">
      {/* Left tree panel */}
      <div className="flex w-[280px] min-w-[240px] flex-col border-r bg-background p-4">
        <h2 className="mb-4 text-lg font-semibold">{t("bs:department.tree")}</h2>
        <LazyDepartmentTree
          controller={tree}
          selectedDeptId={selectedDeptId}
          onSelect={selectNode}
          renderRowSuffix={renderRowSuffix}
          rowRef={(deptId, el) => {
            if (el) rowRefs.current.set(deptId, el)
            else rowRefs.current.delete(deptId)
          }}
        />
        <button
          className="mt-4 w-full rounded-md border border-dashed border-gray-300 py-2 text-sm text-gray-500 hover:border-primary hover:text-primary"
          onClick={() => handleCreateClick()}
        >
          + {t("bs:department.create")}
        </button>
      </div>

      {/* Right panel */}
      <div className="flex-1 overflow-auto p-4">
        {selectedDept ? (
          <Tabs defaultValue="members" className="w-full">
            <div className="mb-4 flex items-center justify-between">
              <div>
                <h2 className="text-lg font-semibold">
                  {selectedDept.name}
                  {selectedDept.status === "archived" ? ` ${t("bs:department.archivedTag")}` : ""}
                </h2>
              </div>
              <TabsList>
                <TabsTrigger value="members">{t("bs:department.members")}</TabsTrigger>
                <TabsTrigger value="settings">{t("bs:department.settings")}</TabsTrigger>
              </TabsList>
            </div>
            <TabsContent value="members">
              <MemberTable
                deptId={selectedDept.dept_id}
                deptName={selectedDept.name}
                dept={selectedDept}
                isArchived={selectedDept.status === "archived"}
                onChanged={handleTreeChange}
                membersRefreshSignal={membersRefreshSignal}
                highlightUserId={memberHighlightUserId}
                onHighlightConsumed={handleMemberHighlightConsumed}
                onRequestLocateMember={handleLocateMemberFromGlobal}
              />
            </TabsContent>
            <TabsContent value="settings">
              <DepartmentSettings
                dept={selectedDept}
                onChanged={handleDepartmentSettingsChanged}
                onMarkAsTenant={canMountTenant ? handleMarkAsTenant : undefined}
              />
            </TabsContent>
          </Tabs>
        ) : (
          <div className="flex h-full items-center justify-center text-muted-foreground">
            {t("bs:department.selectDept")}
          </div>
        )}
      </div>

      {/* Create dialog */}
      {createOpen && (
        <CreateDepartmentDialog
          defaultParentId={createParentId}
          onCreated={handleCreated}
          onClose={() => setCreateOpen(false)}
        />
      )}

      {/* Mount as Child Tenant dialog */}
      {mountTarget && (
        <MountTenantDialog
          deptId={mountTarget.id}
          deptName={mountTarget.name}
          onMounted={handleMounted}
          onClose={() => setMountTarget(null)}
        />
      )}
    </div>
  )
}
