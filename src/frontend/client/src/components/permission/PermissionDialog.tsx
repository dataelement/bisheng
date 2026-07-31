import { AlertTriangle, Loader2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { getResourcePermissionContext } from "~/api/permission";
import type {
  MutateResourceGrantsResult,
  PermissionGrantAssignee,
  ResourcePermissionContext,
  ResourceType,
} from "~/api/permission";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "~/components/ui";
import { useLocalize } from "~/hooks";
import { ModeHeader } from "./ModeHeader";
import { PermissionGrantTab } from "./PermissionGrantTab";
import { PermissionListTab } from "./PermissionListTab";

interface PermissionDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
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
  const [context, setContext] =
    useState<ResourcePermissionContext | null>(null);
  const [assignees, setAssignees] = useState<PermissionGrantAssignee[]>([]);
  const [refreshKey, setRefreshKey] = useState(0);
  const [activeTab, setActiveTab] = useState("roster");
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);

  const loadContext = useCallback(async () => {
    setLoading(true);
    setFailed(false);
    try {
      setContext(
        await getResourcePermissionContext(resourceType, resourceId),
      );
    } catch {
      setContext(null);
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, [resourceId, resourceType]);

  useEffect(() => {
    if (!open) {
      setContext(null);
      setAssignees([]);
      setActiveTab("roster");
      return;
    }
    setActiveTab("roster");
    void loadContext();
  }, [loadContext, open]);

  const handleGrantSuccess = (result: MutateResourceGrantsResult) => {
    setContext((current) =>
      current
        ? { ...current, resource_version: result.resource_version }
        : current,
    );
    setAssignees(result.items);
    setRefreshKey((current) => current + 1);
    setActiveTab("roster");
  };

  const handleModeApplied = async () => {
    setAssignees([]);
    setRefreshKey((current) => current + 1);
    setActiveTab("roster");
    await loadContext();
  };

  const canEditGrants =
    context?.mode === "CUSTOM" && context.can_manage_permission;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="!flex h-[80vh] max-h-[800px] w-[calc(100vw-32px)] max-w-[800px] min-w-0 flex-col gap-0 overflow-hidden p-5">
        <DialogHeader className="shrink-0 text-left">
          <DialogTitle className="text-left">
            {localize("f048_permission.dialog.title")} - {resourceName}
          </DialogTitle>
          <DialogDescription>
            {localize("f048_permission.dialog.description")}
          </DialogDescription>
        </DialogHeader>

        <div className="mt-4 min-h-0 flex-1 overflow-y-auto">
          {loading && (
            <div className="flex min-h-56 items-center justify-center gap-2 text-sm text-[#818181]">
              <Loader2 aria-hidden="true" className="size-4 animate-spin" />
              {localize("f048_permission.dialog.loading")}
            </div>
          )}

          {!loading && failed && (
            <div
              className="flex min-h-56 items-center justify-center gap-2 rounded-lg border border-red-200 bg-red-50 p-5 text-sm text-red-700"
              role="alert"
            >
              <AlertTriangle aria-hidden="true" className="size-4" />
              {localize("f048_permission.dialog.load_failed")}
            </div>
          )}

          {!loading && context && (
            <div className="flex min-h-0 flex-col gap-4">
              <ModeHeader
                resourceType={resourceType}
                resourceId={resourceId}
                context={context}
                onApplied={handleModeApplied}
              />

              <Tabs
                value={activeTab}
                onValueChange={setActiveTab}
                className="min-h-0"
              >
                <TabsList>
                  <TabsTrigger value="roster">
                    {localize("f048_permission.dialog.roster")}
                  </TabsTrigger>
                  {canEditGrants && (
                    <TabsTrigger value="grants">
                      {localize("f048_permission.dialog.manage_grants")}
                    </TabsTrigger>
                  )}
                </TabsList>
                <TabsContent value="roster" className="mt-3">
                  <PermissionListTab
                    resourceType={resourceType}
                    resourceId={resourceId}
                    context={context}
                    refreshKey={refreshKey}
                    showContextHeader={false}
                    onRosterChange={setAssignees}
                  />
                </TabsContent>
                {canEditGrants && (
                  <TabsContent value="grants" className="mt-3">
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
        </div>
      </DialogContent>
    </Dialog>
  );
}
