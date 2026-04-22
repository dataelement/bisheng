import { useCallback, useContext, useEffect, useRef, useState } from "react"
import { useTranslation } from "react-i18next"
import { getDepartmentTreeApi } from "@/controllers/API/department"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { DepartmentTreeNode } from "@/types/api/department"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/bs-ui/tabs"
import { DepartmentTree } from "@/pages/DepartmentPage/components/DepartmentTree"
import { MemberTable } from "@/pages/DepartmentPage/components/MemberTable"
import { DepartmentSettings } from "@/pages/DepartmentPage/components/DepartmentSettings"
import { DepartmentTrafficControl } from "@/pages/DepartmentPage/components/DepartmentTrafficControl"
import { CreateDepartmentDialog } from "@/pages/DepartmentPage/components/CreateDepartmentDialog"
import { locationContext } from "@/contexts/locationContext"

export default function Departments() {
  const { t } = useTranslation()
  const { appConfig } = useContext(locationContext)
  const [tree, setTree] = useState<DepartmentTreeNode[]>([])
  const [selectedDeptId, setSelectedDeptId] = useState<string | null>(null)
  const [selectedDept, setSelectedDept] = useState<DepartmentTreeNode | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [createParentId, setCreateParentId] = useState<number | null>(null)
  const [membersRefreshSignal, setMembersRefreshSignal] = useState(0)
  const [leftPaneWidth, setLeftPaneWidth] = useState(280)
  const isResizingRef = useRef(false)
  const containerRef = useRef<HTMLDivElement | null>(null)

  const loadTree = useCallback(() => {
    captureAndAlertRequestErrorHoc(getDepartmentTreeApi()).then((res) => {
      if (res) {
        setTree(res)
        if (!selectedDeptId && res.length > 0) {
          setSelectedDeptId(res[0].dept_id)
          setSelectedDept(res[0])
        }
      }
    })
  }, [selectedDeptId])

  useEffect(() => {
    loadTree()
  }, [])

  const findNode = useCallback(
    (nodes: DepartmentTreeNode[], deptId: string): DepartmentTreeNode | null => {
      for (const n of nodes) {
        if (n.dept_id === deptId) return n
        const found = findNode(n.children || [], deptId)
        if (found) return found
      }
      return null
    },
    []
  )

  const handleSelect = useCallback((node: DepartmentTreeNode) => {
    setSelectedDeptId(node.dept_id)
    setSelectedDept(node)
  }, [])

  const handleCreateClick = useCallback((parentId?: number) => {
    setCreateParentId(parentId ?? null)
    setCreateOpen(true)
  }, [])

  const handleCreated = useCallback(() => {
    setCreateOpen(false)
    loadTree()
  }, [loadTree])

  const handleTreeChange = useCallback(() => {
    loadTree()
    setMembersRefreshSignal((n) => n + 1)
  }, [loadTree])

  useEffect(() => {
    if (selectedDeptId && tree.length > 0) {
      const node = findNode(tree, selectedDeptId)
      if (node) setSelectedDept(node)
    }
  }, [tree, selectedDeptId, findNode])

  useEffect(() => {
    const handleMouseMove = (event: MouseEvent) => {
      if (!isResizingRef.current) return
      const container = containerRef.current
      if (!container) return
      const rect = container.getBoundingClientRect()
      const relativeX = event.clientX - rect.left
      const MIN_WIDTH = 240
      // Keep enough width for right content and operation buttons.
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
      <div
        className="flex min-w-[240px] flex-col border-r pr-4 pt-2"
        style={{ width: leftPaneWidth }}
      >
        <DepartmentTree
          data={tree}
          selectedDeptId={selectedDeptId}
          onSelect={handleSelect}
          onCreateChild={handleCreateClick}
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
                <span className="text-sm text-muted-foreground">
                  {t("bs:department.memberCount")}: {selectedDept.member_count}
                </span>
              </div>
              <TabsList>
                <TabsTrigger value="members">{t("bs:department.members")}</TabsTrigger>
                <TabsTrigger value="settings">{t("bs:department.settings")}</TabsTrigger>
                {appConfig.isPro && (
                  <TabsTrigger value="traffic-control">{t("bs:department.trafficControl")}</TabsTrigger>
                )}
              </TabsList>
            </div>
            <TabsContent value="members">
              <MemberTable
                deptId={selectedDept.dept_id}
                deptName={selectedDept.name}
                onChanged={handleTreeChange}
                membersRefreshSignal={membersRefreshSignal}
              />
            </TabsContent>
            <TabsContent value="settings">
              <DepartmentSettings dept={selectedDept} tree={tree} onChanged={handleTreeChange} />
            </TabsContent>
            {appConfig.isPro && (
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
          tree={tree}
          defaultParentId={createParentId}
          onCreated={handleCreated}
          onClose={() => setCreateOpen(false)}
        />
      )}
    </div>
  )
}
