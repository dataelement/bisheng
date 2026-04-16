import { useCallback, useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { getDepartmentTreeApi } from "@/controllers/API/department"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { DepartmentTreeNode } from "@/types/api/department"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/bs-ui/tabs"
import { DepartmentTree } from "@/pages/DepartmentPage/components/DepartmentTree"
import { MemberTable } from "@/pages/DepartmentPage/components/MemberTable"
import { DepartmentSettings } from "@/pages/DepartmentPage/components/DepartmentSettings"
import { CreateDepartmentDialog } from "@/pages/DepartmentPage/components/CreateDepartmentDialog"

export default function Departments() {
  const { t } = useTranslation()
  const [tree, setTree] = useState<DepartmentTreeNode[]>([])
  const [selectedDeptId, setSelectedDeptId] = useState<string | null>(null)
  const [selectedDept, setSelectedDept] = useState<DepartmentTreeNode | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [createParentId, setCreateParentId] = useState<number | null>(null)

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
  }, [loadTree])

  useEffect(() => {
    if (selectedDeptId && tree.length > 0) {
      const node = findNode(tree, selectedDeptId)
      if (node) setSelectedDept(node)
    }
  }, [tree, selectedDeptId, findNode])

  return (
    <div className="flex h-[calc(100vh-140px)]">
      {/* Left tree panel */}
      <div className="flex w-[280px] min-w-[240px] flex-col border-r pr-4 pt-2">
        <DepartmentTree
          data={tree}
          selectedDeptId={selectedDeptId}
          onSelect={handleSelect}
          onCreateChild={handleCreateClick}
        />
        <button
          className="mt-4 w-full rounded-md border border-dashed border-gray-300 py-2 text-sm text-gray-500 hover:border-primary hover:text-primary"
          onClick={() => handleCreateClick(tree[0]?.id)}
        >
          + {t("bs:department.create")}
        </button>
      </div>

      {/* Right panel */}
      <div className="flex-1 overflow-auto pl-4 pt-2">
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
              </TabsList>
            </div>
            <TabsContent value="members">
              <MemberTable
                deptId={selectedDept.dept_id}
                deptName={selectedDept.name}
                onChanged={handleTreeChange}
              />
            </TabsContent>
            <TabsContent value="settings">
              <DepartmentSettings dept={selectedDept} tree={tree} onChanged={handleTreeChange} />
            </TabsContent>
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
