import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle,
} from "@/components/bs-ui/dialog"
import { Button } from "@/components/bs-ui/button"
import { Checkbox } from "@/components/bs-ui/checkBox"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/bs-ui/tabs"
import { getGrantableRelationModelsApi, type RelationModel } from "@/controllers/API/permission"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { useCallback, useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { PermissionGrantTab } from "./PermissionGrantTab"
import { PermissionListTab } from "./PermissionListTab"
import { ResourceType, SubjectType } from "./types"

interface PermissionDialogProps {
  open: boolean
  onOpenChange: (v: boolean) => void
  resourceType: ResourceType
  resourceId: string
  resourceName: string
}

const SUBJECT_TABS: Array<{
  value: SubjectType
  labelKey: string
}> = [
  { value: 'user', labelKey: 'subject.user' },
  { value: 'department', labelKey: 'subject.department' },
  { value: 'user_group', labelKey: 'subject.userGroup' },
]

export function PermissionDialog({
  open, onOpenChange, resourceType, resourceId, resourceName,
}: PermissionDialogProps) {
  const { t } = useTranslation('permission')
  const [currentSubjectType, setCurrentSubjectType] = useState<SubjectType>('user')
  const [grantDialogOpen, setGrantDialogOpen] = useState(false)
  const [grantSubjectType, setGrantSubjectType] = useState<SubjectType>('user')
  const [grantIncludeChildren, setGrantIncludeChildren] = useState(true)
  const [refreshKey, setRefreshKey] = useState(0)
  const [grantableModels, setGrantableModels] = useState<RelationModel[]>([])
  const [grantableModelsLoaded, setGrantableModelsLoaded] = useState(false)
  const [useDefaultModels, setUseDefaultModels] = useState(false)

  useEffect(() => {
    if (!open) return
    setCurrentSubjectType('user')
    setGrantSubjectType('user')
    setGrantIncludeChildren(true)
  }, [open])

  useEffect(() => {
    if (grantSubjectType !== 'department' && grantIncludeChildren !== true) {
      setGrantIncludeChildren(true)
    }
  }, [grantIncludeChildren, grantSubjectType])

  useEffect(() => {
    if (!open) return

    setGrantableModelsLoaded(false)
    captureAndAlertRequestErrorHoc(
      getGrantableRelationModelsApi(resourceType, resourceId),
      () => true,
    ).then((res) => {
      if (res === false) {
        setUseDefaultModels(true)
        setGrantableModels([])
        setGrantableModelsLoaded(true)
        return
      }
      if (!res) return
      setUseDefaultModels(false)
      setGrantableModels(res)
      setGrantableModelsLoaded(true)
    })
  }, [open, resourceType, resourceId])

  const handleGrantSuccess = useCallback(() => {
    setRefreshKey((k) => k + 1)
    setCurrentSubjectType(grantSubjectType)
    setGrantDialogOpen(false)
  }, [grantSubjectType])

  const permissionPanel = (
    <Tabs
      value={currentSubjectType}
      onValueChange={(value) => setCurrentSubjectType(value as SubjectType)}
      className="flex min-h-0 flex-1 flex-col"
    >
      <div className="flex items-center justify-between gap-3">
        <TabsList className="w-fit shrink-0 rounded-[6px] border border-[#ECECEC] bg-white p-[3px] shadow-none">
          {SUBJECT_TABS.map((tab) => (
            <TabsTrigger
              key={tab.value}
              value={tab.value}
              className="min-w-0 rounded-[4px] px-3 py-0.5 text-[14px] font-normal leading-[22px] text-[#818181] shadow-none data-[state=active]:border-transparent data-[state=active]:bg-[rgba(51,92,255,0.15)] data-[state=active]:font-medium data-[state=active]:text-[#335CFF] data-[state=active]:shadow-none data-[state=inactive]:border-transparent data-[state=inactive]:text-[#818181]"
            >
              {t(tab.labelKey)}
            </TabsTrigger>
          ))}
        </TabsList>

        <Button
          type="button"
          className="h-8 shrink-0 rounded-[6px] px-3 text-[14px] leading-[22px]"
          onClick={() => {
            setGrantSubjectType(currentSubjectType)
            setGrantIncludeChildren(true)
            setGrantDialogOpen(true)
          }}
        >
          {t('dialog.tabGrant')}
        </Button>
      </div>

      <TabsContent value={currentSubjectType} className="mt-3 min-h-0 flex-1 p-0">
        <PermissionListTab
          resourceType={resourceType}
          resourceId={resourceId}
          refreshKey={refreshKey}
          fixedSubjectType={currentSubjectType}
          prefetchedGrantableModels={grantableModels}
          prefetchedGrantableModelsLoaded={grantableModelsLoaded}
          prefetchedUseDefaultModels={useDefaultModels}
          skipGrantableModelsRequest
        />
      </TabsContent>
    </Tabs>
  )

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="!flex h-[80vh] max-h-[800px] w-[calc(100vw-80px)] max-w-[800px] min-w-0 flex-col gap-0 overflow-hidden p-5">
          <DialogHeader className="shrink-0">
            <DialogTitle>{t('dialog.title')} - {resourceName}</DialogTitle>
            <DialogDescription className="sr-only">
              {t('dialog.title')} - {resourceName}
            </DialogDescription>
          </DialogHeader>

          <div className="mt-4 flex min-h-0 flex-1 flex-col overflow-hidden">
            {permissionPanel}
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={grantDialogOpen} onOpenChange={setGrantDialogOpen}>
        <DialogContent className="!flex h-[80vh] max-h-[800px] w-[calc(100vw-80px)] max-w-[800px] min-w-0 flex-col gap-0 overflow-hidden p-5">
          <DialogHeader className="shrink-0">
            <DialogTitle>
              {t('dialog.tabGrant')} - {resourceName}
            </DialogTitle>
            <DialogDescription className="sr-only">
              {t('dialog.tabGrant')} - {resourceName}
            </DialogDescription>
          </DialogHeader>

          <div className="mt-4 flex min-h-0 flex-1 flex-col overflow-hidden">
            <div className="flex items-center gap-3">
              <div className="inline-flex w-fit shrink-0 items-center justify-center rounded-[6px] border border-[#ECECEC] bg-white p-[3px]">
                {SUBJECT_TABS.map((tab) => (
                  <button
                    key={tab.value}
                    type="button"
                    className={[
                      "min-w-0 rounded-[4px] px-3 py-0.5 text-[14px] leading-[22px] transition-colors",
                      grantSubjectType === tab.value
                        ? "bg-[rgba(51,92,255,0.15)] font-medium text-[#335CFF]"
                        : "font-normal text-[#818181]",
                    ].join(" ")}
                    onClick={() => setGrantSubjectType(tab.value)}
                  >
                    {t(tab.labelKey)}
                  </button>
                ))}
              </div>

              {grantSubjectType === 'department' && (
                <label className="flex shrink-0 cursor-pointer items-center gap-2 text-[14px] leading-[22px] text-[#212121]">
                  <Checkbox
                    checked={grantIncludeChildren}
                    onCheckedChange={(value) => setGrantIncludeChildren(value === true)}
                  />
                  {t('includeChildren')}
                </label>
              )}
            </div>

            <div className="mt-4 min-h-0 flex-1 overflow-hidden">
              <PermissionGrantTab
                resourceType={resourceType}
                resourceId={resourceId}
                onSuccess={handleGrantSuccess}
                prefetchedGrantableModels={grantableModels}
                prefetchedGrantableModelsLoaded={grantableModelsLoaded}
                prefetchedUseDefaultModels={useDefaultModels}
                skipGrantableModelsRequest
                fixedSubjectType={grantSubjectType}
                includeChildren={grantIncludeChildren}
                onIncludeChildrenChange={setGrantIncludeChildren}
                hideDepartmentIncludeChildrenControl
              />
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}
