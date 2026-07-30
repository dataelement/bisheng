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
import type { ResourceType } from "./types"

interface PermissionDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  resourceType: ResourceType
  resourceId: string
  resourceName: string
}

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
  const [activeTab, setActiveTab] = useState("roster")
  const [refreshKey, setRefreshKey] = useState(0)
  const [loading, setLoading] = useState(false)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    if (!open) return
    let cancelled = false
    setContext(null)
    setAssignees([])
    setActiveTab("roster")
    setFailed(false)
    setLoading(true)
    void getResourcePermissionContextApi(resourceType, resourceId)
      .then((result) => {
        if (!cancelled) setContext(result)
      })
      .catch(() => {
        if (!cancelled) setFailed(true)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [open, resourceId, resourceType])

  const handleRosterChange = useCallback(
    (nextAssignees: PermissionGrantAssignee[]) => {
      setAssignees(nextAssignees)
    },
    [],
  )

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
    setActiveTab("roster")
    setRefreshKey((current) => current + 1)
  }

  const handleGrantSuccess = (result: MutateResourceGrantsResult) => {
    setContext((current) =>
      current
        ? { ...current, resource_version: result.resource_version }
        : current,
    )
    setActiveTab("roster")
    setRefreshKey((current) => current + 1)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex h-[85vh] max-h-[860px] w-[calc(100vw-48px)] max-w-4xl min-w-0 flex-col gap-0 overflow-hidden p-5">
        <DialogHeader className="shrink-0">
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
            className="mt-4 flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-900"
            role="alert"
          >
            <AlertTriangle aria-hidden="true" className="size-4" />
            {t("dialog.loadFailed")}
          </p>
        )}

        {context && !loading && !failed && (
          <div className="mt-4 flex min-h-0 flex-1 flex-col gap-4">
            <ModeHeader
              resourceType={resourceType}
              resourceId={resourceId}
              context={context}
              onApplied={handleModeApplied}
            />

            <Tabs
              value={activeTab}
              onValueChange={setActiveTab}
              className="flex min-h-0 flex-1 flex-col"
            >
              <TabsList className="h-auto min-h-11 shrink-0 self-start">
                <TabsTrigger value="roster">
                  {t("dialog.roster")}
                </TabsTrigger>
                {context.can_manage_permission &&
                  context.mode === "CUSTOM" && (
                    <TabsTrigger value="manage">
                      {t("dialog.manageGrants")}
                    </TabsTrigger>
                  )}
              </TabsList>

              <TabsContent
                value="roster"
                className="min-h-0 flex-1 overflow-y-auto py-2"
              >
                <PermissionListTab
                  resourceType={resourceType}
                  resourceId={resourceId}
                  context={context}
                  refreshKey={refreshKey}
                  showContextHeader={false}
                  onRosterChange={handleRosterChange}
                />
              </TabsContent>

              {context.can_manage_permission &&
                context.mode === "CUSTOM" && (
                  <TabsContent
                    value="manage"
                    className="min-h-0 flex-1 overflow-y-auto py-2"
                  >
                    <PermissionGrantTab
                      resourceType={resourceType}
                      resourceId={resourceId}
                      context={context}
                      assignees={assignees}
                      onSuccess={handleGrantSuccess}
                    />
                  </TabsContent>
                )}
            </Tabs>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
