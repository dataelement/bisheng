import { LazyDepartmentTree, useLazyDepartmentTree } from "@/components/bs-comp/department"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/bs-ui/tabs"
import { locationContext } from "@/contexts/locationContext"
import { userContext } from "@/contexts/userContext"
import { getDepartmentApi } from "@/controllers/API/department"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { CreateDepartmentDialog } from "@/pages/DepartmentPage/components/CreateDepartmentDialog"
import { DepartmentSettings } from "@/pages/DepartmentPage/components/DepartmentSettings"
import { DepartmentTrafficControl } from "@/pages/DepartmentPage/components/DepartmentTrafficControl"
import { MemberTable } from "@/pages/DepartmentPage/components/MemberTable"
import { MountTenantDialog } from "@/pages/DepartmentPage/components/MountTenantDialog"
import { DepartmentTreeNode } from "@/types/api/department"
import { Plus } from "lucide-react"
import { useCallback, useContext, useEffect, useRef, useState } from "react"
import { useTranslation } from "react-i18next"

export default function Departments() {
  const { t } = useTranslation()
  const { appConfig } = useContext(locationContext)
  const { user } = useContext(userContext)
  /** 与系统页「组织同步」一致：仅平台超级管理员（role=admin） */
  const isSuperAdmin = user?.role === "admin"
  const showTrafficControlTab = isSuperAdmin && appConfig.isPro
  const multiTenantEnabled = !!appConfig?.multiTenantEnabled

  // F038: lazy management nav tree (see DepartmentPage/index for the rationale).
  const tree = useLazyDepartmentTree({ includeArchived: true, autoExpandRoots: true })

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

  const [leftPaneWidth, setLeftPaneWidth] = useState(280)
  const isResizingRef = useRef(false)
  const containerRef = useRef<HTMLDivElement | null>(null)

  const selectNode = useCallback((node: DepartmentTreeNode) => {
    setSelectedId(node.id)
    setSelectedSnapshot(node)
  }, [])

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

  const handleTreeChange = useCallback(
    (removedDeptId?: string) => {
      void tree.refreshAll()
      setMembersRefreshSignal((n) => n + 1)
      if (removedDeptId && selectedDeptId === removedDeptId) {
        setSelectedId(null)
        setSelectedSnapshot(null)
      }
    },
    [tree, selectedDeptId]
  )

  const handleLocateMemberFromGlobal = useCallback(
    async ({ primaryDeptDeptId, userId }: { primaryDeptDeptId: string; userId: number }) => {
      setMemberHighlightUserId(userId)
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

  useEffect(() => {
    const handleMouseMove = (event: MouseEvent) => {
      if (!isResizingRef.current) return
      const container = containerRef.current
      if (!container) return
      const rect = container.getBoundingClientRect()
      const relativeX = event.clientX - rect.left
      const MIN_WIDTH = 240
      const MAX_WIDTH = Math.min(520, Math.max(MIN_WIDTH, rect.width - 320))
      setLeftPaneWidth(Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, relativeX)))
    }

    const stopResizing = () => {
      isResizingRef.current = false
      document.body.style.cursor = ""
      document.body.style.userSelect = ""
    }

    window.addEventListener("mousemove", handleMouseMove)
    window.addEventListener("mouseup", stopResizing)

    return () => {
      window.removeEventListener("mousemove", handleMouseMove)
      window.removeEventListener("mouseup", stopResizing)
    }
  }, [])

  return (
    <div ref={containerRef} className="flex h-[calc(100vh-140px)]">
      {/* Left tree panel */}
      <div className="flex min-w-[240px] flex-col border-r pr-4 pt-2" style={{ width: leftPaneWidth }}>
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

      <div
        role="separator"
        aria-orientation="vertical"
        className="w-1 cursor-col-resize bg-transparent hover:bg-border"
        onMouseDown={() => {
          isResizingRef.current = true
          document.body.style.cursor = "col-resize"
          document.body.style.userSelect = "none"
        }}
      />

      {/* Right panel */}
      <div className="min-w-0 flex-1 overflow-auto pl-4 pt-2">
        {selectedDept ? (
          <Tabs defaultValue="members" className="w-full">
            <div className="mb-4 flex items-center justify-between">
              <div>
                <h3 className="text-base font-semibold">{selectedDept.name}</h3>
              </div>
              <TabsList>
                <TabsTrigger value="members">{t("bs:department.members")}</TabsTrigger>
                <TabsTrigger value="settings">{t("bs:department.settings")}</TabsTrigger>
                {showTrafficControlTab && (
                  <TabsTrigger value="traffic-control">{t("bs:department.trafficControl")}</TabsTrigger>
                )}
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
                onChanged={handleTreeChange}
                onMarkAsTenant={multiTenantEnabled && user?.is_global_super ? handleMarkAsTenant : undefined}
              />
            </TabsContent>
            {showTrafficControlTab && (
              <TabsContent value="traffic-control">
                <DepartmentTrafficControl dept={selectedDept} />
              </TabsContent>
            )}
          </Tabs>
        ) : (
          <div className="flex h-full items-center justify-center text-muted-foreground">
            {t("bs:department.selectDept")}
          </div>
        )}
      </div>

      {createOpen && (
        <CreateDepartmentDialog
          defaultParentId={createParentId}
          onCreated={handleCreated}
          onClose={() => setCreateOpen(false)}
        />
      )}

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
