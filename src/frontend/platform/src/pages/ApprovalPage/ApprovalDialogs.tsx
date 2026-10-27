import { Button, Input, Textarea } from '@bisheng/ui';

import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";

import { Tag } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import type { ApproverSource } from "./approvalMetadata";
import { approverSourceLabel } from "./approverSources";
import { useContext } from "react";
import { locationContext } from "@/contexts/locationContext";
import { ApproverUserPicker } from "./components/ApproverUserPicker";
import { FlowDialog } from "./FlowDialog";
import { NodeDialog } from "./NodeDialog";
import { RouteDialog } from "./RouteDialog";
import { AddScenarioDialog } from "./ScenarioDialog";

import type { useApprovalController } from "./useApprovalController";
interface ApprovalDialogsProps {
  controller: ReturnType<typeof useApprovalController>;
}
export function ApprovalDialogs({ controller }: ApprovalDialogsProps) {
  const { appConfig } = useContext(locationContext);
  const {
    showAddScenario,
    presets,
    existingCodes,
    setShowAddScenario,
    handleAddScenario,
    routeDialog,
    flows,
    activeConditionFields,
    allowPassRoute,
    setRouteDialog,
    handleSaveRoute,
    flowDialog,
    setFlowDialog,
    handleSaveFlow,
    nodeDialog,
    activeSourceTypes,
    setNodeDialog,
    handleSaveNode,
    flowPreviewDialog,
    setFlowPreviewDialog,
    t,
    editScenarioDialog,
    setEditScenarioDialog,
    handleSaveScenarioName,
    exceptionPickerOpen,
    setExceptionPickerOpen,
    exceptionPickerTempIds,
    exceptionPickerTempNames,
    setExceptionPickerTempIds,
    setExceptionPickerTempNames,
    exceptionPickerItem,
    handleRetryException,
    cancelDialogItem,
    setCancelDialogItem,
    setCancelReason,
    cancelReason,
    handleCancelException,
  } = controller;
  return (
    <>
      {" "}
      <AddScenarioDialog
        open={showAddScenario}
        presets={presets}
        existingCodes={existingCodes}
        onClose={() => setShowAddScenario(false)}
        onConfirm={(preset) => void handleAddScenario(preset)}
      />
      <RouteDialog
        open={routeDialog.open}
        initial={routeDialog.initial}
        flows={flows}
        conditionFields={activeConditionFields}
        allowPassRoute={allowPassRoute}
        onClose={() => setRouteDialog({ open: false, initial: {} })}
        onConfirm={(data) => void handleSaveRoute(data)}
      />
      <FlowDialog
        open={flowDialog.open}
        initial={flowDialog.initial}
        onClose={() => setFlowDialog({ open: false, initial: {} })}
        onConfirm={(data) => void handleSaveFlow(data)}
      />
      <NodeDialog
        open={nodeDialog.open}
        initial={nodeDialog.initial}
        allowedSourceTypes={activeSourceTypes}
        onClose={() => setNodeDialog({ open: false, initial: {} })}
        onConfirm={(data) => void handleSaveNode(data)}
      />
      {/* Flow preview dialog */}
      <Dialog
        open={flowPreviewDialog.open}
        onOpenChange={(v) => !v && setFlowPreviewDialog({ open: false, flowName: "", nodes: [] })}
      >
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{flowPreviewDialog.flowName}</DialogTitle>
          </DialogHeader>
          <div className="py-2 max-h-[60vh] overflow-y-auto">
            {flowPreviewDialog.nodes.length === 0 ? (
              <div className="py-8 text-center text-sm text-muted-foreground">{t("approvalPage.noNodes")}</div>
            ) : (
              <div className="space-y-3">
                {flowPreviewDialog.nodes.map((node, idx) => {
                  const sources: ApproverSource[] = (node.approver_config?.sources as ApproverSource[]) ?? [];
                  return (
                    <div key={node.id} className="rounded-lg border border-border p-3">
                      <div className="flex items-center gap-2">
                        <span className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
                          {idx + 1}
                        </span>
                        <span className="text-sm font-medium text-foreground">{node.node_name || node.node_code}</span>
                        <Tag size="small" className="ml-auto shrink-0 whitespace-nowrap">
                          {node.node_mode === "and" ? t("approvalPage.nodeModeAnd") : t("approvalPage.nodeModeOr")}
                        </Tag>
                      </div>
                      {sources.length > 0 && (
                        <div className="mt-2 flex flex-wrap gap-1.5 pl-8">
                          {sources.map((src) => {
                            const userNames: string[] = src.user_names ?? src.userNames ?? [];
                            if (src.type === "direct_user" && userNames.length > 0) {
                              return userNames.map((name: string) => (
                                <Tag
                                  key={`${src.type}-${name}`}
                                  size="small"
                                  icon={<Outlined.People size={12} />}
                                  className="whitespace-nowrap"
                                >
                                  {name}
                                </Tag>
                              ));
                            }
                            return (
                              <Tag
                                key={src.type}
                                size="small"
                                icon={<Outlined.People size={12} />}
                                className="whitespace-nowrap"
                              >
                                {approverSourceLabel(src.type, t, src.label, !!appConfig.multiTenantEnabled)}
                              </Tag>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>
      {/* Edit scenario name dialog */}
      <Dialog
        open={editScenarioDialog.open}
        onOpenChange={(v) => !v && setEditScenarioDialog({ open: false, scenario: null, name: "" })}
      >
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>{t("approvalPage.edit")}</DialogTitle>
          </DialogHeader>
          <div className="py-2">
            <label className="block text-sm text-muted-foreground">
              {t("approvalPage.scenarioSection")}
              <Input value={editScenarioDialog.name} onChange={(e) => setEditScenarioDialog((prev) => ({ ...prev, name: e.target.value }))} onKeyDown={(e) => e.key === "Enter" && void handleSaveScenarioName()} className={"mt-1 block w-full"} />
            </label>
          </div>
          <DialogFooter>
            <Button size="medium" variant="outlined" type="button" onClick={() => setEditScenarioDialog({ open: false, scenario: null, name: "" })} color="default">
              {t("approvalPage.cancel")}
            </Button>
            <Button size="medium" variant="solid" type="button" disabled={!editScenarioDialog.name.trim()} onClick={() => void handleSaveScenarioName()} color="primary">
              {t("approvalPage.save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      {/* ── Exception Approver Picker Dialog ────────────────────────────────── */}
      <Dialog open={exceptionPickerOpen} onOpenChange={(v) => !v && setExceptionPickerOpen(false)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{t("approvalPage.assignApproversAction")}</DialogTitle>
          </DialogHeader>
          <ApproverUserPicker
            value={exceptionPickerTempIds}
            names={exceptionPickerTempNames}
            onChange={(ids, names) => {
              setExceptionPickerTempIds(ids);
              setExceptionPickerTempNames(names);
            }}
          />
          <DialogFooter>
            <Button size="medium" variant="outlined" type="button" onClick={() => setExceptionPickerOpen(false)} color="default">
              {t("approvalPage.cancel")}
            </Button>
            <Button size="medium" variant="solid" type="button" disabled={!exceptionPickerTempIds.length} onClick={async () => {
                if (!exceptionPickerItem || !exceptionPickerTempIds.length) return;
                setExceptionPickerOpen(false);
                await handleRetryException(exceptionPickerItem, {
                  action: "assign_approvers",
                  approver_user_ids: exceptionPickerTempIds,
                });
              }} color="primary">
              {t("approvalPage.save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      {/* ── Cancel Exception Dialog ──────────────────────────────────────────── */}
      {cancelDialogItem && (
        <Dialog
          open
          onOpenChange={(open) => {
            if (!open) {
              setCancelDialogItem(null);
              setCancelReason("");
            }
          }}
        >
          <DialogContent className="max-w-md">
            <DialogHeader>
              <DialogTitle>{t("approvalPage.cancelExceptionTitle")}</DialogTitle>
            </DialogHeader>
            <div className="py-2 space-y-3">
              <p className="text-sm text-muted-foreground">{t("approvalPage.cancelExceptionHint")}</p>
              <Textarea rows={3} value={cancelReason} onChange={(e) => setCancelReason(e.target.value)} placeholder={t("approvalPage.cancelReasonPlaceholder") as string} textareaClassName={"w-full resize-none"} />
            </div>
            <DialogFooter>
              <Button size="medium" variant="outlined" type="button" onClick={() => {
                  setCancelDialogItem(null);
                  setCancelReason("");
                }} color="default">
                {t("approvalPage.cancelBtn")}
              </Button>
              <Button size="medium" variant="solid" type="button" onClick={() => void handleCancelException()} color="danger">
                {t("approvalPage.confirmCancelException")}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </>
  );
}
