import { Button } from "@/components/bs-ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/bs-ui/dialog"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/bs-ui/tabs"
import {
  getResourcePermissionContextApi,
  type ApplyPermissionModeDraftResult,
  type MutateResourceGrantsResult,
  type PermissionGrantAssignee,
  type ResourcePermissionContext,
} from "@/controllers/API/permission"
import { AlertTriangle, Loader2 } from "lucide-react"
import { useCallback, useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { ModeHeader } from "./ModeHeader"
import { PermissionGrantTab } from "./PermissionGrantTab"
import { PermissionListTab } from "./PermissionListTab"
import type { ResourceType, SubjectType } from "./types"

interface PermissionDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  resourceType: ResourceType
  resourceId: string
  resourceName: string
}

const SUBJECT_TABS: Array<{ value: SubjectType; labelKey: string }> = [
  { value: "user", labelKey: "subject.user" },
  { value: "department", labelKey: "subject.department" },
  { value: "user_group", labelKey: "subject.userGroup" },
]

export function PermissionDialog({
  open,
  onOpenChange,
  resourceType,
  resourceId,
  resourceName,
}: PermissionDialogProps) {
  const { t } = useTranslation("permission")
  const [context, setContext] = useState<ResourcePermissionContext | null>(
    null,
  )
  const [assignees, setAssignees] = useState<PermissionGrantAssignee[]>([])
  const [subjectType, setSubjectType] = useState<SubjectType>("user")
  const [grantDialogOpen, setGrantDialogOpen] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)
  const [loading, setLoading] = useState(false)
  const [failed, setFailed] = useState(false)

  const loadContext = useCallback(async () => {
    setLoading(true)
    setFailed(false)
    try {
      setContext(
        await getResourcePermissionContextApi(resourceType, resourceId),
      )
    } catch {
      setContext(null)
      setFailed(true)
    } finally {
      setLoading(false)
    }
  }, [resourceId, resourceType])

  useEffect(() => {
    if (!open) {
      setContext(null)
      setAssignees([])
      setGrantDialogOpen(false)
      return
    }
    setSubjectType("user")
    void loadContext()
  }, [loadContext, open])

  const handleModeApplied = (result: ApplyPermissionModeDraftResult) => {
    setContext((current) =>
      current
        ? {
            ...current,
            mode: result.mode,
            resource_version: result.resource_version,
          }
        : current,
    )
    setRefreshKey((current) => current + 1)
  }

  const handleGrantSuccess = (result: MutateResourceGrantsResult) => {
    setContext((current) =>
      current
        ? { ...current, resource_version: result.resource_version }
        : current,
    )
    setAssignees(result.items)
    setRefreshKey((current) => current + 1)
    setGrantDialogOpen(false)
  }

  const canAddPermission =
    context?.mode === "CUSTOM" && context.can_manage_permission

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="flex h-[80vh] max-h-[800px] w-[calc(100vw-80px)] max-w-[800px] min-w-0 flex-col gap-0 overflow-hidden p-0">
          <DialogHeader className="shrink-0 px-5 pb-4 pt-5">
            <DialogTitle>
              {t("dialog.title")} - {resourceName}
            </DialogTitle>
            <DialogDescription className="sr-only">
              {t("dialog.description")}
            </DialogDescription>
          </DialogHeader>

          {loading && (
            <div
              className="flex min-h-56 flex-1 items-center justify-center gap-2 text-sm text-muted-foreground"
              role="status"
            >
              <Loader2 aria-hidden="true" className="size-4 animate-spin" />
              {t("dialog.loading")}
            </div>
          )}

          {failed && !loading && (
            <p
              className="mx-5 flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-900"
              role="alert"
            >
              <AlertTriangle aria-hidden="true" className="size-4" />
              {t("dialog.loadFailed")}
            </p>
          )}

          {context && !loading && !failed && (
            <div className="flex min-h-0 flex-1 flex-col">
              <ModeHeader
                resourceType={resourceType}
                resourceId={resourceId}
                context={context}
                onApplied={handleModeApplied}
              />

              <Tabs
                value={subjectType}
                onValueChange={(value) =>
                  setSubjectType(value as SubjectType)
                }
                className="flex min-h-0 flex-1 flex-col px-5 pb-5 pt-4"
              >
                <div className="flex items-center justify-between gap-3">
                  <TabsList className="h-auto w-fit shrink-0 rounded-[6px] border border-[#ECECEC] bg-white p-[3px] shadow-none">
                    {SUBJECT_TABS.map((tab) => (
                      <TabsTrigger
                        key={tab.value}
                        value={tab.value}
                        className="min-w-0 rounded-[4px] px-3 py-0.5 text-[14px] font-normal leading-[22px] text-[#818181] shadow-none data-[state=active]:border-transparent data-[state=active]:bg-primary/10 data-[state=active]:font-medium data-[state=active]:text-primary data-[state=active]:shadow-none data-[state=inactive]:border-transparent"
                      >
                        {t(tab.labelKey)}
                      </TabsTrigger>
                    ))}
                  </TabsList>

                  {canAddPermission && (
                    <Button
                      type="button"
                      className="h-8 shrink-0 rounded-[6px] px-3 text-[14px] leading-[22px]"
                      onClick={() => setGrantDialogOpen(true)}
                    >
                      {t("dialog.tabGrant")}
                    </Button>
                  )}
                </div>

                <TabsContent
                  value={subjectType}
                  className="mt-3 min-h-0 flex-1 overflow-hidden p-0"
                >
                  <PermissionListTab
                    resourceType={resourceType}
                    resourceId={resourceId}
                    context={context}
                    refreshKey={refreshKey}
                    fixedSubjectType={subjectType}
                    onRosterChange={setAssignees}
                    onMutationSuccess={handleGrantSuccess}
                  />
                </TabsContent>
              </Tabs>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {context && canAddPermission && (
        <Dialog open={grantDialogOpen} onOpenChange={setGrantDialogOpen}>
          <DialogContent className="flex h-[80vh] max-h-[800px] w-[calc(100vw-80px)] max-w-[800px] min-w-0 flex-col gap-0 overflow-hidden p-5">
            <DialogHeader className="shrink-0">
              <DialogTitle>
                {t("dialog.tabGrant")} - {resourceName}
              </DialogTitle>
              <DialogDescription className="sr-only">
                {t("dialog.tabGrant")} - {resourceName}
              </DialogDescription>
            </DialogHeader>
            <div className="mt-4 min-h-0 flex-1 overflow-y-auto">
              <PermissionGrantTab
                resourceType={resourceType}
                resourceId={resourceId}
                context={context}
                assignees={assignees}
                fixedSubjectType={subjectType}
                showExistingAssignees={false}
                onSuccess={handleGrantSuccess}
              />
            </div>
          </DialogContent>
        </Dialog>
      )}
    </>
  )
}
