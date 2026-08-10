import { Input } from "@/components/bs-ui/input"
import { Label } from "@/components/bs-ui/label"
import { Separator } from "@/components/bs-ui/separator"
import { TreeDepartmentSelect } from "@/components/bs-comp/department/TreeDepartmentSelect"
import type { DepartmentTreeNode } from "@/types/api/department"
import { useTranslation } from "react-i18next"

interface DepartmentBasicInfoSectionProps {
  name: string
  shortName: string
  tree: DepartmentTreeNode[]
  parentTreeNodes: DepartmentTreeNode[]
  parentId: number | null
  originalParentId: number | null
  isSynced: boolean
  isArchived: boolean
  isDefaultRoot: boolean
  canEditParent: boolean
  onNameChange: (value: string) => void
  onShortNameChange: (value: string) => void
  onParentChange: (value: number | null) => void
}

const FORM_CONTROL_WIDTH = "w-full max-w-md"

function findParentDisplay(
  nodes: DepartmentTreeNode[],
  parentId: number | null
): string {
  if (parentId === null) return "-"
  for (const node of nodes) {
    if (node.id === parentId) return node.name
    const found = findParentDisplay(node.children || [], parentId)
    if (found !== "-") return found
  }
  return "-"
}

export function DepartmentBasicInfoSection({
  name,
  shortName,
  tree,
  parentTreeNodes,
  parentId,
  originalParentId,
  isSynced,
  isArchived,
  isDefaultRoot,
  canEditParent,
  onNameChange,
  onShortNameChange,
  onParentChange,
}: DepartmentBasicInfoSectionProps) {
  const { t } = useTranslation()

  return (
    <section className="space-y-4">
      <div>
        <h3 className="mb-2 text-base font-semibold tracking-tight text-foreground">
          {t("bs:department.sectionBasic")}
        </h3>
        <Separator />
      </div>
      <div className="space-y-1.5">
        <Label>{t("bs:department.name")}</Label>
        <Input
          value={name}
          onChange={(event) => onNameChange(event.target.value)}
          maxLength={50}
          disabled={isSynced || isArchived}
          className={FORM_CONTROL_WIDTH}
        />
      </div>
      <div className="space-y-1.5">
        <Label>{t("bs:department.shortName")}</Label>
        <Input
          value={shortName}
          onChange={(event) => onShortNameChange(event.target.value)}
          placeholder={t("bs:department.shortNamePlaceholder")}
          maxLength={64}
          disabled={isArchived}
          className={FORM_CONTROL_WIDTH}
        />
        <p className="max-w-md text-xs text-muted-foreground">
          {t("bs:department.shortNameLength")}
        </p>
      </div>
      {!isDefaultRoot && (
        <div className="space-y-1.5">
          <Label>{t("bs:department.parentDept")}</Label>
          {canEditParent ? (
            <TreeDepartmentSelect
              nodes={parentTreeNodes}
              value={parentId}
              onChange={onParentChange}
              className={FORM_CONTROL_WIDTH}
              placeholder={t("bs:department.selectDept")}
              searchPlaceholder={t("bs:department.parentDept")}
              modal={false}
            />
          ) : (
            <Input
              value={findParentDisplay(tree, originalParentId)}
              disabled
              className={FORM_CONTROL_WIDTH}
            />
          )}
        </div>
      )}
    </section>
  )
}
