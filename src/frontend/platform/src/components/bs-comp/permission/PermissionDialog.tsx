import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle,
} from "@/components/bs-ui/dialog"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/bs-ui/tabs"
import { getGrantableRelationModelsApi, type RelationModel } from "@/controllers/API/permission"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { useCallback, useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { PermissionGrantTab } from "./PermissionGrantTab"
import { PermissionListTab } from "./PermissionListTab"
import { ResourceType } from "./types"

interface PermissionDialogProps {
  open: boolean
  onOpenChange: (v: boolean) => void
  resourceType: ResourceType
  resourceId: string
  resourceName: string
}

export function PermissionDialog({
  open, onOpenChange, resourceType, resourceId, resourceName,
}: PermissionDialogProps) {
  const { t } = useTranslation('permission')
  const [activeTab, setActiveTab] = useState('list')
  const [refreshKey, setRefreshKey] = useState(0)
  const [grantableModels, setGrantableModels] = useState<RelationModel[]>([])
  const [grantableModelsLoaded, setGrantableModelsLoaded] = useState(false)
  const [useDefaultModels, setUseDefaultModels] = useState(false)

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
    setActiveTab('list')
  }, [])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[calc(100vh-2rem)] flex-col overflow-hidden sm:max-w-[680px]">
        <DialogHeader className="shrink-0">
          <DialogTitle>{t('dialog.title')} - {resourceName}</DialogTitle>
          <DialogDescription className="sr-only">
            {t('dialog.tabList')} / {t('dialog.tabGrant')}
          </DialogDescription>
        </DialogHeader>
        <Tabs value={activeTab} onValueChange={setActiveTab} className="flex min-h-0 flex-1 flex-col">
          <TabsList className="shrink-0 self-start">
            <TabsTrigger value="list">{t('dialog.tabList')}</TabsTrigger>
            <TabsTrigger value="grant">{t('dialog.tabGrant')}</TabsTrigger>
          </TabsList>
          <TabsContent value="list" className="min-h-0 flex-1 overflow-hidden">
            <PermissionListTab
              resourceType={resourceType}
              resourceId={resourceId}
              refreshKey={refreshKey}
              prefetchedGrantableModels={grantableModels}
              prefetchedGrantableModelsLoaded={grantableModelsLoaded}
              prefetchedUseDefaultModels={useDefaultModels}
              skipGrantableModelsRequest
            />
          </TabsContent>
          <TabsContent value="grant" className="min-h-0 flex-1 overflow-hidden">
            <PermissionGrantTab
              resourceType={resourceType}
              resourceId={resourceId}
              onSuccess={handleGrantSuccess}
              prefetchedGrantableModels={grantableModels}
              prefetchedGrantableModelsLoaded={grantableModelsLoaded}
              prefetchedUseDefaultModels={useDefaultModels}
              skipGrantableModelsRequest
            />
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  )
}
