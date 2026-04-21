import { useState, useCallback } from "react";
import { useLocalize } from "~/hooks";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "~/components/ui/Dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "~/components/ui/Tabs";
import { PermissionListTab } from "./PermissionListTab";
import { PermissionGrantTab } from "./PermissionGrantTab";
import type { ResourceType } from "~/api/permission";

interface PermissionDialogProps {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  resourceType: ResourceType;
  resourceId: string;
  resourceName: string;
}

export function PermissionDialog({
  open,
  onOpenChange,
  resourceType,
  resourceId,
  resourceName,
}: PermissionDialogProps) {
  const localize = useLocalize();
  const [activeTab, setActiveTab] = useState("list");
  const [refreshKey, setRefreshKey] = useState(0);

  const handleGrantSuccess = useCallback(() => {
    setRefreshKey((k) => k + 1);
    setActiveTab("list");
  }, []);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[680px]">
        <DialogHeader>
          <DialogTitle>
            {localize("com_permission.dialog_title")} - {resourceName}
          </DialogTitle>
        </DialogHeader>
        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <TabsList className="bg-surface-primary-alt p-1">
            <TabsTrigger value="list">
              {localize("com_permission.tab_list")}
            </TabsTrigger>
            <TabsTrigger value="grant">
              {localize("com_permission.tab_grant")}
            </TabsTrigger>
          </TabsList>
          <TabsContent value="list" className="p-0">
            <PermissionListTab
              resourceType={resourceType}
              resourceId={resourceId}
              refreshKey={refreshKey}
            />
          </TabsContent>
          <TabsContent value="grant" className="p-0">
            <PermissionGrantTab
              resourceType={resourceType}
              resourceId={resourceId}
              onSuccess={handleGrantSuccess}
            />
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}
