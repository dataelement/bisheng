import { useEffect, useMemo, useState } from "react";
import {
  decideApprovalTaskApi,
  getApprovalInstanceDetailApi,
  getMyApprovalTaskDetailApi,
  listMyApprovalRequestsApi,
  listMyApprovalTasksApi,
  revokeMenuAccessGrantApi,
  resubmitApprovalInstanceApi,
  type ApprovalCenterTab,
  type ApprovalInstanceDetail,
  type ApprovalInstanceItem,
  type ApprovalTaskDetail,
  type ApprovalTaskItem,
  withdrawApprovalInstanceApi,
} from "~/api/approval";
import { useToastContext } from "~/Providers";
import { NotificationSeverity } from "~/common";
import { useLocalize } from "~/hooks";
import { cn } from "~/utils";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../ui/Dialog";

type ApprovalCenterTarget = {
  tab?: ApprovalCenterTab;
  taskId?: number | null;
  instanceId?: number | null;
};

export interface ApprovalCenterDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  target?: ApprovalCenterTarget;
}

function getTaskId(item?: ApprovalTaskItem | ApprovalTaskDetail | null): number | null {
  const raw = item?.task_id ?? item?.id;
  const num = Number(raw);
  return Number.isFinite(num) ? num : null;
}

function getInstanceId(item?: ApprovalInstanceItem | ApprovalInstanceDetail | null): number | null {
  const raw = item?.instance_id ?? item?.id;
  const num = Number(raw);
  return Number.isFinite(num) ? num : null;
}

function getStatusText(localize: ReturnType<typeof useLocalize>, status?: string | null) {
  const normalized = String(status || "").toLowerCase();
  switch (normalized) {
    case "pending":
      return localize("com_approval_status_pending");
    case "approved":
      return localize("com_approval_status_approved");
    case "rejected":
      return localize("com_approval_status_rejected");
    case "withdrawn":
      return localize("com_approval_status_withdrawn");
    case "execute_failed":
      return localize("com_approval_status_execute_failed");
    default:
      return status || "--";
  }
}

function getDisplayTitle(item: Record<string, any> | null | undefined, fallback: string) {
  return (
    item?.business_name ||
    item?.title ||
    item?.detail?.menu_name ||
    item?.payload_snapshot?.menu_name ||
    fallback
  );
}

function renderDetailRows(detail: Record<string, any> | null | undefined) {
  if (!detail) return [];
  return Object.entries(detail).filter(([, value]) => value !== undefined && value !== null && value !== "");
}

/** Translate raw snapshot field keys to human-readable labels */
function localizeFieldKey(key: string, localize: ReturnType<typeof useLocalize>): string {
  const map: Record<string, string> = {
    menu_key:   localize("com_approval_field_menu_key" as any),
    menu_name:  localize("com_approval_field_menu_name" as any),
    reason:     localize("com_approval_field_reason" as any),
    space_type: localize("com_approval_field_space_type" as any),
    channel_id: localize("com_approval_field_channel_id" as any),
    space_id:   localize("com_approval_field_space_id" as any),
  };
  return map[key] ?? key;
}

export function ApprovalCenterDialog({
  open,
  onOpenChange,
  target,
}: ApprovalCenterDialogProps) {
  const localize = useLocalize();
  const { showToast } = useToastContext();
  const [activeTab, setActiveTab] = useState<ApprovalCenterTab>(target?.tab ?? "my_tasks");
  const [taskItems, setTaskItems] = useState<ApprovalTaskItem[]>([]);
  const [requestItems, setRequestItems] = useState<ApprovalInstanceItem[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState<number | null>(target?.taskId ?? null);
  const [selectedInstanceId, setSelectedInstanceId] = useState<number | null>(target?.instanceId ?? null);
  const [taskDetail, setTaskDetail] = useState<ApprovalTaskDetail | null>(null);
  const [requestDetail, setRequestDetail] = useState<ApprovalInstanceDetail | null>(null);
  const [loadingList, setLoadingList] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);

  const resetTarget = () => {
    setActiveTab(target?.tab ?? "my_tasks");
    setSelectedTaskId(target?.taskId ?? null);
    setSelectedInstanceId(target?.instanceId ?? null);
  };

  const loadTasks = async (preferredTaskId?: number | null) => {
    setLoadingList(true);
    try {
      const response = await listMyApprovalTasksApi();
      setTaskItems(response.data);
      const nextId = preferredTaskId ?? getTaskId(response.data[0]);
      setSelectedTaskId(nextId);
      if (nextId) {
        setLoadingDetail(true);
        const detail = await getMyApprovalTaskDetailApi(nextId);
        setTaskDetail(detail);
      } else {
        setTaskDetail(null);
      }
    } finally {
      setLoadingList(false);
      setLoadingDetail(false);
    }
  };

  const loadRequests = async (preferredInstanceId?: number | null) => {
    setLoadingList(true);
    try {
      const response = await listMyApprovalRequestsApi();
      setRequestItems(response.data);
      const nextId = preferredInstanceId ?? getInstanceId(response.data[0]);
      setSelectedInstanceId(nextId);
      if (nextId) {
        setLoadingDetail(true);
        const detail = await getApprovalInstanceDetailApi(nextId);
        setRequestDetail(detail);
      } else {
        setRequestDetail(null);
      }
    } finally {
      setLoadingList(false);
      setLoadingDetail(false);
    }
  };

  useEffect(() => {
    if (!open) return;
    resetTarget();
  }, [open, target?.instanceId, target?.tab, target?.taskId]);

  useEffect(() => {
    if (!open) return;
    if (activeTab === "my_tasks") {
      void loadTasks(target?.taskId ?? selectedTaskId);
      return;
    }
    void loadRequests(target?.instanceId ?? selectedInstanceId);
  }, [open, activeTab]);

  const currentDetailRows = useMemo(() => {
    const detail = activeTab === "my_tasks"
      ? (taskDetail?.detail_snapshot ?? taskDetail?.detail ?? taskDetail?.payload_snapshot)
      : (requestDetail?.detail_snapshot ?? requestDetail?.payload_snapshot);
    return renderDetailRows(detail);
  }, [activeTab, requestDetail, taskDetail]);

  const openTask = async (taskId: number) => {
    setSelectedTaskId(taskId);
    setLoadingDetail(true);
    try {
      setTaskDetail(await getMyApprovalTaskDetailApi(taskId));
    } finally {
      setLoadingDetail(false);
    }
  };

  const openRequest = async (instanceId: number) => {
    setSelectedInstanceId(instanceId);
    setLoadingDetail(true);
    try {
      setRequestDetail(await getApprovalInstanceDetailApi(instanceId));
    } finally {
      setLoadingDetail(false);
    }
  };

  const runTaskDecision = async (action: "approve" | "reject") => {
    if (!selectedTaskId) return;
    setActionLoading(true);
    try {
      const detail = await decideApprovalTaskApi(selectedTaskId, { action });
      setTaskDetail(detail);
      await loadTasks(selectedTaskId);
      showToast({
        message: localize("com_approval_toast_success"),
        severity: NotificationSeverity.SUCCESS,
      });
    } catch {
      showToast({
        message: localize("com_approval_toast_failed"),
        severity: NotificationSeverity.INFO,
      });
    } finally {
      setActionLoading(false);
    }
  };

  const runWithdraw = async () => {
    if (!selectedInstanceId) return;
    setActionLoading(true);
    try {
      const detail = await withdrawApprovalInstanceApi(selectedInstanceId, {});
      setRequestDetail(detail);
      await loadRequests(selectedInstanceId);
      showToast({
        message: localize("com_approval_toast_success"),
        severity: NotificationSeverity.SUCCESS,
      });
    } catch {
      showToast({
        message: localize("com_approval_toast_failed"),
        severity: NotificationSeverity.INFO,
      });
    } finally {
      setActionLoading(false);
    }
  };

  const runRevokeGrant = async () => {
    if (!selectedInstanceId) return;
    setActionLoading(true);
    try {
      await revokeMenuAccessGrantApi(selectedInstanceId, {});
      await loadRequests(selectedInstanceId);
      showToast({
        message: localize("com_approval_toast_success"),
        severity: NotificationSeverity.SUCCESS,
      });
    } catch {
      showToast({
        message: localize("com_approval_toast_failed"),
        severity: NotificationSeverity.INFO,
      });
    } finally {
      setActionLoading(false);
    }
  };

  const runResubmit = async () => {
    if (!selectedInstanceId) return;
    setActionLoading(true);
    try {
      const detail = await resubmitApprovalInstanceApi(selectedInstanceId, {});
      setRequestDetail(detail);
      await loadRequests(selectedInstanceId);
      showToast({
        message: localize("com_approval_toast_success"),
        severity: NotificationSeverity.SUCCESS,
      });
    } catch {
      showToast({
        message: localize("com_approval_toast_failed"),
        severity: NotificationSeverity.INFO,
      });
    } finally {
      setActionLoading(false);
    }
  };

  const listItems = activeTab === "my_tasks" ? taskItems : requestItems;
  const selectedId = activeTab === "my_tasks" ? selectedTaskId : selectedInstanceId;
  const selectedTitle = activeTab === "my_tasks"
    ? getDisplayTitle(taskDetail, localize("com_approval_empty_detail"))
    : getDisplayTitle(requestDetail, localize("com_approval_empty_detail"));
  const selectedStatus = activeTab === "my_tasks"
    ? getStatusText(localize, taskDetail?.status)
    : getStatusText(localize, requestDetail?.status);
  const canApproveTask = activeTab === "my_tasks" && String(taskDetail?.status || "").toLowerCase() === "pending";
  const canWithdrawRequest = activeTab === "my_requests" && String(requestDetail?.status || "").toLowerCase() === "pending";
  const canResubmitRequest = activeTab === "my_requests" && String(requestDetail?.status || "").toLowerCase() === "rejected";
  const canRevokeGrant =
    activeTab === "my_requests" &&
    String(requestDetail?.scenario_code || "").toLowerCase() === "menu_access_request" &&
    String(requestDetail?.status || "").toLowerCase() === "approved";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="h-[80vh] max-h-[820px] w-[calc(100vw-64px)] max-w-[1080px] rounded-2xl p-0">
        <div className="flex h-full flex-col overflow-hidden rounded-2xl bg-white">
          <DialogHeader className="border-b border-[#f2f3f5] px-6 py-5 text-left">
            <DialogTitle className="text-[18px] font-semibold text-[#1d2129]">
              {localize("com_approval_center_title")}
            </DialogTitle>
          </DialogHeader>

          <div className="flex items-center gap-2 border-b border-[#f2f3f5] px-6 py-3">
            <button
              type="button"
              className={cn(
                "rounded-lg px-4 py-2 text-[14px] transition-colors",
                activeTab === "my_tasks"
                  ? "bg-[#e8f3ff] text-[#165dff]"
                  : "text-[#4e5969] hover:bg-[#f7f8fa]",
              )}
              onClick={() => setActiveTab("my_tasks")}
            >
              {localize("com_approval_my_tasks")}
            </button>
            <button
              type="button"
              className={cn(
                "rounded-lg px-4 py-2 text-[14px] transition-colors",
                activeTab === "my_requests"
                  ? "bg-[#e8f3ff] text-[#165dff]"
                  : "text-[#4e5969] hover:bg-[#f7f8fa]",
              )}
              onClick={() => setActiveTab("my_requests")}
            >
              {localize("com_approval_my_requests")}
            </button>
          </div>

          <div className="grid min-h-0 flex-1 grid-cols-[320px_minmax(0,1fr)]">
            <div className="min-h-0 border-r border-[#f2f3f5] bg-[#fafbfc]">
              {loadingList ? (
                <div className="flex h-full items-center justify-center text-[14px] text-[#86909c]">
                  {localize("com_approval_loading")}
                </div>
              ) : listItems.length === 0 ? (
                <div className="flex h-full items-center justify-center px-6 text-center text-[14px] text-[#86909c]">
                  {localize("com_approval_empty_list")}
                </div>
              ) : (
                <div className="h-full overflow-y-auto p-3">
                  {listItems.map((item) => {
                    const itemId = activeTab === "my_tasks" ? getTaskId(item as ApprovalTaskItem) : getInstanceId(item as ApprovalInstanceItem);
                    const active = itemId === selectedId;
                    return (
                      <button
                        key={`${activeTab}-${itemId}`}
                        type="button"
                        className={cn(
                          "mb-2 flex w-full flex-col rounded-xl border px-4 py-3 text-left transition-colors",
                          active
                            ? "border-[#165dff] bg-white shadow-[0_4px_20px_rgba(22,93,255,0.08)]"
                            : "border-transparent bg-white hover:border-[#d9e3f0]",
                        )}
                        onClick={() => {
                          if (!itemId) return;
                          if (activeTab === "my_tasks") {
                            void openTask(itemId);
                            return;
                          }
                          void openRequest(itemId);
                        }}
                      >
                        <span className="text-[14px] font-medium text-[#1d2129]">
                          {getDisplayTitle(item, localize("com_approval_empty_detail"))}
                        </span>
                        <span className="mt-2 text-[12px] text-[#86909c]">
                          {getStatusText(localize, item.status)}
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>

            <div className="min-h-0 overflow-y-auto px-6 py-5">
              {loadingDetail ? (
                <div className="flex h-full min-h-[280px] items-center justify-center text-[14px] text-[#86909c]">
                  {localize("com_approval_loading")}
                </div>
              ) : !selectedId ? (
                <div className="flex h-full min-h-[280px] items-center justify-center text-[14px] text-[#86909c]">
                  {localize("com_approval_empty_detail")}
                </div>
              ) : (
                <div className="space-y-5">
                  <div>
                    <h3 className="text-[20px] font-semibold text-[#1d2129]">{selectedTitle}</h3>
                    <p className="mt-2 text-[14px] text-[#4e5969]">
                      {localize("com_approval_status_label")} {selectedStatus}
                    </p>
                  </div>

                  {currentDetailRows.length > 0 && (
                    <div className="rounded-2xl border border-[#f2f3f5] bg-[#fafbfc] p-4">
                      <div className="mb-3 text-[14px] font-medium text-[#1d2129]">
                        {localize("com_approval_detail_section")}
                      </div>
                      <div className="space-y-2 text-[14px] text-[#4e5969]">
                        {currentDetailRows.map(([key, value]) => (
                          <div key={key} className="flex gap-3">
                            <span className="w-[140px] shrink-0 text-[#86909c]">{localizeFieldKey(key, localize)}</span>
                            <span className="break-all">{Array.isArray(value) ? value.join(", ") : String(value)}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {requestDetail?.action_logs && requestDetail.action_logs.length > 0 && (
                    <div className="rounded-2xl border border-[#f2f3f5] bg-white p-4">
                      <div className="mb-3 text-[14px] font-medium text-[#1d2129]">
                        {localize("com_approval_progress_section")}
                      </div>
                      <div className="space-y-3">
                        {requestDetail.action_logs.map((log, index) => (
                          <div key={`${log.id ?? index}`} className="rounded-xl bg-[#fafbfc] px-4 py-3">
                            <div className="text-[14px] text-[#1d2129]">
                              {log.operator_user_name || "--"} · {log.action || "--"}
                            </div>
                            <div className="mt-1 text-[12px] text-[#86909c]">{log.create_time || "--"}</div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  <div className="flex flex-wrap gap-3">
                    {canApproveTask && (
                      <>
                        <button
                          type="button"
                          disabled={actionLoading}
                          className="rounded-lg border border-[#00b42a] px-4 py-2 text-[14px] text-[#00b42a] hover:bg-[#f0fff4] disabled:cursor-not-allowed disabled:opacity-60"
                          onClick={() => void runTaskDecision("approve")}
                        >
                          {localize("com_approval_action_approve")}
                        </button>
                        <button
                          type="button"
                          disabled={actionLoading}
                          className="rounded-lg border border-[#f53f3f] px-4 py-2 text-[14px] text-[#f53f3f] hover:bg-[#fff2f0] disabled:cursor-not-allowed disabled:opacity-60"
                          onClick={() => void runTaskDecision("reject")}
                        >
                          {localize("com_approval_action_reject")}
                        </button>
                      </>
                    )}
                    {canWithdrawRequest && (
                      <button
                        type="button"
                        disabled={actionLoading}
                        className="rounded-lg border border-[#165dff] px-4 py-2 text-[14px] text-[#165dff] hover:bg-[#f2f7ff] disabled:cursor-not-allowed disabled:opacity-60"
                        onClick={() => void runWithdraw()}
                      >
                        {localize("com_approval_action_withdraw")}
                      </button>
                    )}
                    {canResubmitRequest && (
                      <button
                        type="button"
                        disabled={actionLoading}
                        className="rounded-lg border border-[#722ed1] px-4 py-2 text-[14px] text-[#722ed1] hover:bg-[#f9f0ff] disabled:cursor-not-allowed disabled:opacity-60"
                        onClick={() => void runResubmit()}
                      >
                        {localize("com_approval_action_resubmit")}
                      </button>
                    )}
                    {canRevokeGrant && (
                      <button
                        type="button"
                        disabled={actionLoading}
                        className="rounded-lg border border-[#ff7d00] px-4 py-2 text-[14px] text-[#ff7d00] hover:bg-[#fff7e8] disabled:cursor-not-allowed disabled:opacity-60"
                        onClick={() => void runRevokeGrant()}
                      >
                        {localize("com_approval_action_revoke_grant")}
                      </button>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
