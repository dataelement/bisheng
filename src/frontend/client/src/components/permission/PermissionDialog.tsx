import { AlertTriangle, Loader2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { getResourcePermissionContext } from "~/api/permission";
import type {
  ApplyPermissionModeDraftResult,
  MutateResourceGrantsResult,
  PermissionGrantAssignee,
  ResourcePermissionContext,
  ResourceType,
  SubjectType,
} from "~/api/permission";
import {
  Button,
  Checkbox,
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

const SUBJECT_TABS: Array<{ value: SubjectType; labelKey: string }> = [
  { value: "user", labelKey: "f048_permission.subject.user" },
  {
    value: "department",
    labelKey: "f048_permission.subject.department",
  },
  {
    value: "user_group",
    labelKey: "f048_permission.subject.user_group",
  },
];

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
  const [subjectType, setSubjectType] = useState<SubjectType>("user");
  const [grantSubjectType, setGrantSubjectType] =
    useState<SubjectType>("user");
  const [grantIncludeChildren, setGrantIncludeChildren] = useState(false);
  const [grantDialogOpen, setGrantDialogOpen] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
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
      setGrantDialogOpen(false);
      return;
    }
    setSubjectType("user");
    setGrantSubjectType("user");
    setGrantIncludeChildren(false);
    void loadContext();
  }, [loadContext, open]);

  useEffect(() => {
    if (grantSubjectType !== "department") {
      setGrantIncludeChildren(false);
    }
  }, [grantSubjectType]);

  const handleGrantSuccess = (result: MutateResourceGrantsResult) => {
    setContext((current) =>
      current
        ? { ...current, resource_version: result.resource_version }
        : current,
    );
    setAssignees(result.items);
    setRefreshKey((current) => current + 1);
    setGrantDialogOpen(false);
  };

  const handleModeApplied = (result: ApplyPermissionModeDraftResult) => {
    setContext((current) =>
      current
        ? {
            ...current,
            mode: result.mode,
            resource_version: result.resource_version,
          }
        : current,
    );
    setRefreshKey((current) => current + 1);
  };

  const canAddPermission =
    context?.mode === "CUSTOM" && context.can_manage_permission;
  const dialogClassName =
    "!flex h-[80vh] max-h-[800px] w-[calc(100vw-80px)] max-w-[800px] min-w-0 flex-col gap-0 overflow-hidden p-0 max-[768px]:fixed max-[768px]:inset-0 max-[768px]:h-[100dvh] max-[768px]:max-h-[100dvh] max-[768px]:w-full max-[768px]:max-w-none max-[768px]:translate-x-0 max-[768px]:translate-y-0 max-[768px]:rounded-none";

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent
          className={dialogClassName}
          onOpenAutoFocus={(event) => event.preventDefault()}
        >
          <DialogHeader className="shrink-0 px-5 pb-4 pt-5 text-left max-[768px]:px-4">
            <DialogTitle className="text-left">
              {localize("f048_permission.dialog.title")} - {resourceName}
            </DialogTitle>
            <DialogDescription className="sr-only">
              {localize("f048_permission.dialog.description")}
            </DialogDescription>
          </DialogHeader>

          {loading && (
            <div
              className="flex min-h-56 flex-1 items-center justify-center gap-2 text-sm text-[#818181]"
              role="status"
            >
              <Loader2 aria-hidden="true" className="size-4 animate-spin" />
              {localize("f048_permission.dialog.loading")}
            </div>
          )}

          {!loading && failed && (
            <div
              className="mx-5 flex min-h-32 items-center justify-center gap-2 rounded-lg border border-red-200 bg-red-50 p-5 text-sm text-red-700 max-[768px]:mx-4"
              role="alert"
            >
              <AlertTriangle aria-hidden="true" className="size-4" />
              {localize("f048_permission.dialog.load_failed")}
            </div>
          )}

          {!loading && context && (
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
                className="flex min-h-0 flex-1 flex-col px-5 pb-5 pt-4 max-[768px]:px-4"
              >
                <div className="flex items-center justify-between gap-3">
                  <TabsList className="w-fit shrink-0 rounded-md border border-[#ECECEC] bg-white p-[3px] shadow-none">
                    {SUBJECT_TABS.map((tab) => (
                      <TabsTrigger
                        key={tab.value}
                        value={tab.value}
                        className="min-w-0 rounded px-3 py-0.5 text-sm font-normal leading-[22px] text-[#818181] shadow-none data-[state=active]:bg-blue-500/[0.07] data-[state=active]:font-medium data-[state=active]:text-blue-500 data-[state=active]:shadow-none"
                      >
                        {localize(tab.labelKey)}
                      </TabsTrigger>
                    ))}
                  </TabsList>

                  {canAddPermission && (
                    <Button
                      type="button"
                      className="h-8 shrink-0 rounded-md px-3 text-sm leading-[22px]"
                      onClick={() => {
                        setGrantSubjectType(subjectType);
                        setGrantIncludeChildren(false);
                        setGrantDialogOpen(true);
                      }}
                    >
                      {localize("com_permission.tab_grant")}
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
          <DialogContent
            className={`${dialogClassName} !p-5 max-[768px]:!p-4`}
            onOpenAutoFocus={(event) => event.preventDefault()}
          >
            <DialogHeader className="shrink-0 text-left">
              <DialogTitle className="text-left">
                {localize("com_permission.tab_grant")} - {resourceName}
              </DialogTitle>
              <DialogDescription className="sr-only">
                {localize("com_permission.tab_grant")} - {resourceName}
              </DialogDescription>
            </DialogHeader>

            <div className="mt-4 flex min-h-0 flex-1 flex-col overflow-hidden">
              <div className="flex flex-wrap items-center gap-3">
                <div className="inline-flex w-fit shrink-0 items-center justify-center rounded-md border border-[#ECECEC] bg-white p-[3px]">
                  {SUBJECT_TABS.map((tab) => (
                    <button
                      key={tab.value}
                      type="button"
                      aria-pressed={grantSubjectType === tab.value}
                      className={`min-w-0 rounded px-3 py-0.5 text-sm leading-[22px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/40 ${
                        grantSubjectType === tab.value
                          ? "bg-blue-500/[0.07] font-medium text-blue-500"
                          : "font-normal text-[#818181]"
                      }`}
                      onClick={() => setGrantSubjectType(tab.value)}
                    >
                      {localize(tab.labelKey)}
                    </button>
                  ))}
                </div>

                {grantSubjectType === "department" && (
                  <label className="flex shrink-0 cursor-pointer items-center gap-2 text-sm leading-[22px] text-[#212121]">
                    <Checkbox
                      checked={grantIncludeChildren}
                      onCheckedChange={(checked) =>
                        setGrantIncludeChildren(checked === true)
                      }
                    />
                    {localize(
                      "f048_permission.source.include_children",
                    )}
                  </label>
                )}
              </div>

              <div className="mt-4 min-h-0 flex-1 overflow-hidden">
                <PermissionGrantTab
                  resourceType={resourceType}
                  resourceId={resourceId}
                  context={context}
                  assignees={assignees}
                  fixedSubjectType={grantSubjectType}
                  includeChildren={grantIncludeChildren}
                  onIncludeChildrenChange={setGrantIncludeChildren}
                  hideDepartmentIncludeChildrenControl
                  legacyAddLayout
                  showExistingAssignees={false}
                  onSuccess={handleGrantSuccess}
                />
              </div>
            </div>
          </DialogContent>
        </Dialog>
      )}
    </>
  );
}
