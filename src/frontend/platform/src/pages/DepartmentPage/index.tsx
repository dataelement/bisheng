import { useCallback, useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { getDepartmentTreeApi } from "@/controllers/API/department"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { DepartmentTreeNode } from "@/types/api/department"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/bs-ui/tabs"
import { DepartmentTree } from "./components/DepartmentTree"
import { MemberTable } from "./components/MemberTable"
import { DepartmentSettings } from "./components/DepartmentSettings"
import { CreateDepartmentDialog } from "./components/CreateDepartmentDialog"

export default function DepartmentPage() {
  const { t } = useTranslation()
  const [tree, setTree] = useState<DepartmentTreeNode[]>([])
  const [selectedDeptId, setSelectedDeptId] = useState<string | null>(null)
  const [selectedDept, setSelectedDept] = useState<DepartmentTreeNode | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [createParentId, setCreateParentId] = useState<number | null>(null)
  const [membersRefreshSignal, setMembersRefreshSignal] = useState(0)
  const [memberHighlightUserId, setMemberHighlightUserId] = useState<number | null>(null)
  const [treeScrollRequest, setTreeScrollRequest] = useState<{
    deptId: string
    requestId: number
  } | null>(null)

  const loadTree = useCallback(() => {
    captureAndAlertRequestErrorHoc(getDepartmentTreeApi()).then((res) => {
      if (res) {
        setTree(res)
        // Auto-select first root if nothing selected
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

  // Find node in tree by dept_id
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

  const handleSelect = useCallback(
    (node: DepartmentTreeNode) => {
      setSelectedDeptId(node.dept_id)
      setSelectedDept(node)
    },
    []
  )

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
  }, [loadTree])

  const handleLocateMemberFromGlobal = useCallback(
    ({
      primaryDeptDeptId,
      userId,
    }: {
      primaryDeptDeptId: string
      userId: number
    }) => {
      setSelectedDeptId(primaryDeptDeptId)
      const node = findNode(tree, primaryDeptDeptId)
      if (node) setSelectedDept(node)
      setMemberHighlightUserId(userId)
      setTreeScrollRequest((prev) => ({
        deptId: primaryDeptDeptId,
        requestId: (prev?.requestId ?? 0) + 1,
      }))
    },
    [tree, findNode]
  )

  const handleTreeScrollHandled = useCallback(() => {
    setTreeScrollRequest(null)
  }, [])

  const handleMemberHighlightConsumed = useCallback(() => {
    setMemberHighlightUserId(null)
  }, [])

  // After tree reload, update selectedDept reference
  useEffect(() => {
    if (selectedDeptId && tree.length > 0) {
      const node = findNode(tree, selectedDeptId)
      if (node) setSelectedDept(node)
    }
  }, [tree, selectedDeptId, findNode])

  return (
    <div className="flex h-full w-full">
      {/* Left tree panel */}
      <div className="flex w-[280px] min-w-[240px] flex-col border-r bg-background p-4">
        <h2 className="mb-4 text-lg font-semibold">{t("bs:department.tree")}</h2>
        <DepartmentTree
          data={tree}
          selectedDeptId={selectedDeptId}
          onSelect={handleSelect}
          onCreateChild={handleCreateClick}
          scrollRequest={treeScrollRequest}
          onScrollRequestHandled={handleTreeScrollHandled}
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
                <span className="text-sm text-muted-foreground">
                  {t("bs:department.memberCount")}: {selectedDept.member_count}
                </span>
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
                tree={tree}
                onChanged={handleTreeChange}
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
          tree={tree}
          defaultParentId={createParentId}
          onCreated={handleCreated}
          onClose={() => setCreateOpen(false)}
        />
      )}
    </div>
  )
}
