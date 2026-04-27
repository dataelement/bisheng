import { SubjectSearchDepartment } from "@/components/bs-comp/permission/SubjectSearchDepartment"
import type { SelectedSubject } from "@/components/bs-comp/permission/types"
import { Button } from "@/components/bs-ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/bs-ui/dialog"
import { Label } from "@/components/bs-ui/label"
import { toast } from "@/components/bs-ui/toast/use-toast"
import {
  batchCreateDepartmentKnowledgeSpacesApi,
  getDepartmentKnowledgeSpacesApi,
  type DepartmentKnowledgeSpaceSummary,
} from "@/controllers/API/departmentKnowledgeSpace"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { useEffect, useMemo, useState } from "react"
import { useTranslation } from "react-i18next"

interface DepartmentSpaceDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreated?: () => void
}

export function DepartmentSpaceDialog({
  open,
  onOpenChange,
  onCreated,
}: DepartmentSpaceDialogProps) {
  const { t } = useTranslation("bs")
  const [selected, setSelected] = useState<SelectedSubject[]>([])
  const [departmentSpaces, setDepartmentSpaces] = useState<DepartmentKnowledgeSpaceSummary[]>([])
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (!open) {
      setSelected([])
      setDepartmentSpaces([])
      setLoading(false)
      setSubmitting(false)
      return
    }

    let active = true
    setLoading(true)
    captureAndAlertRequestErrorHoc(getDepartmentKnowledgeSpacesApi({ order_by: "name" })).then(
      (res) => {
        if (!active || res === false || !Array.isArray(res)) return
        setDepartmentSpaces(res)
      }
    ).finally(() => {
      if (active) setLoading(false)
    })

    return () => {
      active = false
    }
  }, [open])

  const existingDepartmentIds = useMemo(
    () =>
      departmentSpaces
        .map((space) => space.department_id)
        .filter((departmentId): departmentId is number => typeof departmentId === "number"),
    [departmentSpaces]
  )

  const existingDepartmentIdSet = useMemo(
    () => new Set(existingDepartmentIds),
    [existingDepartmentIds]
  )

  const selectedDepartmentIds = useMemo(
    () =>
      selected
        .map((subject) => subject.id)
        .filter((departmentId) => !existingDepartmentIdSet.has(departmentId)),
    [existingDepartmentIdSet, selected]
  )

  const handleSubmit = async () => {
    if (!selectedDepartmentIds.length) {
      toast({
        title: t("prompt"),
        variant: "warning",
        description: t("departmentSpace.selectRequired"),
      })
      return
    }

    setSubmitting(true)
    const res = await captureAndAlertRequestErrorHoc(
      batchCreateDepartmentKnowledgeSpacesApi(selectedDepartmentIds)
    )
    setSubmitting(false)

    if (res === false) return

    toast({
      title: t("prompt"),
      variant: "success",
      description: t("departmentSpace.submitSuccess", {
        count: Array.isArray(res) ? res.length : selectedDepartmentIds.length,
      }),
    })
    onCreated?.()
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[680px]">
        <DialogHeader>
          <DialogTitle>{t("departmentSpace.configure")}</DialogTitle>
          <DialogDescription>
            {t("departmentSpace.dialogHint")}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div className="rounded-md border bg-muted/20 px-4 py-3 text-sm text-muted-foreground">
            <p>{t("departmentSpace.dialogHint")}</p>
            <p className="mt-2">
              {loading
                ? t("loading")
                : t("departmentSpace.createdHint", { count: departmentSpaces.length })}
            </p>
          </div>

          <div className="space-y-2">
            <Label>{t("departmentSpace.selectionLabel")}</Label>
            <SubjectSearchDepartment
              value={selected}
              onChange={setSelected}
              allowOrganizationTree
              includeChildren={false}
              onIncludeChildrenChange={() => undefined}
              showIncludeChildrenToggle={false}
              disabledIds={existingDepartmentIds}
              disabledLabel={t("departmentSpace.createdBadge")}
            />
            <p className="text-xs text-muted-foreground">
              {t("departmentSpace.selectedCount", { count: selectedDepartmentIds.length })}
            </p>
          </div>

          <div className="space-y-2">
            <Label>{t("departmentSpace.defaultRules")}</Label>
            <div className="rounded-md border px-4 py-3 text-sm text-muted-foreground">
              <ul className="list-disc space-y-1 pl-5">
                <li>{t("departmentSpace.defaultNameRule")}</li>
                <li>{t("departmentSpace.defaultDescriptionRule")}</li>
                <li>{t("departmentSpace.defaultAuthRule")}</li>
                <li>{t("departmentSpace.defaultReleaseRule")}</li>
              </ul>
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button onClick={handleSubmit} disabled={submitting || !selectedDepartmentIds.length}>
            {submitting ? t("departmentSpace.submitting") : t("departmentSpace.createAction")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
