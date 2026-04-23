import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/bs-ui/dialog"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/bs-ui/tabs"
import { useCallback, useState } from "react"
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

  const handleGrantSuccess = useCallback(() => {
    setRefreshKey((k) => k + 1)
    setActiveTab('list')
  }, [])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[680px]">
        <DialogHeader>
          <DialogTitle>{t('dialog.title')} - {resourceName}</DialogTitle>
        </DialogHeader>
        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <TabsList>
            <TabsTrigger value="list">{t('dialog.tabList')}</TabsTrigger>
            <TabsTrigger value="grant">{t('dialog.tabGrant')}</TabsTrigger>
          </TabsList>
          <TabsContent value="list">
            <PermissionListTab
              resourceType={resourceType}
              resourceId={resourceId}
              refreshKey={refreshKey}
            />
          </TabsContent>
          <TabsContent value="grant">
            <PermissionGrantTab
              resourceType={resourceType}
              resourceId={resourceId}
              onSuccess={handleGrantSuccess}
            />
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  )
}
