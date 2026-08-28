import { Tabs, Tag } from "@bisheng/ui";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  decideApprovalTaskApi,
  getApprovalInstanceDetailApi,
  getMyApprovalTaskDetailApi,
  listMyApprovalRequestsApi,
  listMyApprovalTasksApi,
  revokeMenuAccessGrantApi,
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
import { Dialog, DialogContent } from "../ui/Dialog";
import { ExpandableSearchField } from "../ui/ExpandableSearchField";
import { RequestDetailPanel, TaskDetailPanel } from "./ApprovalDetailPanels";
import {
  IN_PROGRESS_STATUSES,
  StatusBadge,
  formatTime,
  formatTitle,
  getId,
  type RequestsFilter,
  type TaskFilter,
} from "./approvalPresentation";

export interface ApprovalPaneProps {
  /** Whether the hosting dialog is open — drives the initial data load. */
  open: boolean;
  activeTab: Extract<ApprovalCenterTab, "my_tasks" | "my_requests">;
  target?: { taskId?: number | null; instanceId?: number | null };
  /** Compact (<768px) master-detail state, owned by the dialog shell. */
  compactView: "list" | "detail";
  setCompactView: (view: "list" | "detail") => void;
  /** Fired after any action that can change the pending-task count. */
  onPendingCountMaybeChanged?: () => void;
  /**
   * Rendered at the top of the LIST column, not above the whole pane — the detail
   * column then runs the full height of its container instead of starting below a
   * full-width header strip.
   */
  listHeader?: ReactNode;
}

export function ApprovalPane({
  open,
  activeTab,
  target,
  compactView,
  setCompactView,
  onPendingCountMaybeChanged,
  listHeader,
}: ApprovalPaneProps) {
  const localize = useLocalize();
  const { showToast } = useToastContext();

  const [taskFilter, setTaskFilter] = useState<TaskFilter>("pending_me");
  const [requestsFilter, setRequestsFilter] = useState<RequestsFilter>("in_progress");

  const [taskItems, setTaskItems] = useState<ApprovalTaskItem[]>([]);
  const [requestItems, setRequestItems] = useState<ApprovalInstanceItem[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState<number | null>(null);
  const [selectedInstanceId, setSelectedInstanceId] = useState<number | null>(null);
  const [taskDetail, setTaskDetail] = useState<ApprovalTaskDetail | null>(null);
  const [requestDetail, setRequestDetail] = useState<ApprovalInstanceDetail | null>(null);
  const [loadingList, setLoadingList] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [decisionComment, setDecisionComment] = useState("");
  const [withdrawDialogOpen, setWithdrawDialogOpen] = useState(false);
  const [withdrawReason, setWithdrawReason] = useState("");
  const [revokeDialogOpen, setRevokeDialogOpen] = useState(false);
  const [revokeReason, setRevokeReason] = useState("");

  const filteredTaskItems = useMemo(() => {
    const byStatus = taskFilter === "pending_me"
      ? taskItems.filter((t) => t.status === "pending")
      : taskItems.filter((t) => t.status !== "pending");
    if (!searchQuery.trim()) return byStatus;
    const q = searchQuery.toLowerCase();
    return byStatus.filter((t) =>
      (t.business_name ?? "").toLowerCase().includes(q) ||
      (t.applicant_user_name ?? "").toLowerCase().includes(q) ||
      (t.applicant_department_name ?? "").toLowerCase().includes(q) ||
      (t.current_node_name ?? "").toLowerCase().includes(q),
    );
  }, [taskItems, taskFilter, searchQuery]);

  const filteredRequestItems = useMemo(() => {
    const byStatus = requestsFilter === "in_progress"
      ? requestItems.filter((i) => IN_PROGRESS_STATUSES.has(i.status ?? ""))
      : requestItems.filter((i) => !IN_PROGRESS_STATUSES.has(i.status ?? ""));
    if (!searchQuery.trim()) return byStatus;
    const q = searchQuery.toLowerCase();
    return byStatus.filter((i) =>
      (i.business_name ?? "").toLowerCase().includes(q) ||
      (i.applicant_user_name ?? "").toLowerCase().includes(q) ||
      (i.applicant_department_name ?? "").toLowerCase().includes(q) ||
      (i.current_node_name ?? "").toLowerCase().includes(q) ||
      (i.current_approver_names ?? "").toLowerCase().includes(q),
    );
  }, [requestItems, requestsFilter, searchQuery]);

  const toast = (ok: boolean) => showToast({
    message: localize(ok ? "com_approval_toast_success" : "com_approval_toast_failed"),
    severity: ok ? NotificationSeverity.SUCCESS : NotificationSeverity.INFO,
  });

  const loadTasks = async (preferredId?: number | null, preferredInstanceId?: number | null) => {
    setLoadingList(true);
    try {
      const resp = await listMyApprovalTasksApi();
      setTaskItems(resp.data);
      // Prefer the explicit task id; otherwise resolve the task from the notification's
      // instance id. Channel/space subscribe approval notifications only carry instance_id,
      // so without this fallback the jump would land on the first task instead of the right one.
      let resolvedTask: ApprovalTaskItem | null =
        preferredId ? resp.data.find((t) => getId(t, "task") === preferredId) ?? null : null;
      if (!resolvedTask && preferredInstanceId) {
        const matches = resp.data.filter((t) => t.instance_id === preferredInstanceId);
        resolvedTask = matches.find((t) => t.status === "pending") ?? matches[0] ?? null;
      }
      // Switch the sub-filter so the resolved task is actually visible in the left list.
      let targetFilter = taskFilter;
      if (resolvedTask) {
        targetFilter = resolvedTask.status === "pending" ? "pending_me" : "processed";
        if (targetFilter !== taskFilter) setTaskFilter(targetFilter);
      }
      const visibleItems = targetFilter === "pending_me"
        ? resp.data.filter((t) => t.status === "pending")
        : resp.data.filter((t) => t.status !== "pending");
      const nextId = (resolvedTask ? getId(resolvedTask, "task") : null) ?? getId(visibleItems[0], "task");
      setSelectedTaskId(nextId);
      if (nextId) { setLoadingDetail(true); setTaskDetail(await getMyApprovalTaskDetailApi(nextId)); }
      else setTaskDetail(null);
    } finally { setLoadingList(false); setLoadingDetail(false); }
  };

  const loadRequests = async (preferredId?: number | null) => {
    setLoadingList(true);
    try {
      const resp = await listMyApprovalRequestsApi();
      setRequestItems(resp.data);
      // If there's a preferred instance, derive the correct filter tab from its status so
      // the item is actually visible in the left panel (not hidden by the current filter).
      let targetFilter = requestsFilter;
      if (preferredId) {
        const prefItem = resp.data.find((i) => getId(i, "instance") === preferredId);
        if (prefItem) {
          const prefInProgress = IN_PROGRESS_STATUSES.has(prefItem.status ?? "");
          targetFilter = prefInProgress ? "in_progress" : "completed";
          if (targetFilter !== requestsFilter) setRequestsFilter(targetFilter);
        }
      }
      const visibleItems = targetFilter === "in_progress"
        ? resp.data.filter((i) => IN_PROGRESS_STATUSES.has(i.status ?? ""))
        : resp.data.filter((i) => !IN_PROGRESS_STATUSES.has(i.status ?? ""));
      const validPreferred = preferredId && resp.data.some((i) => getId(i, "instance") === preferredId) ? preferredId : null;
      const nextId = validPreferred ?? getId(visibleItems[0], "instance");
      setSelectedInstanceId(nextId);
      if (nextId) { setLoadingDetail(true); setRequestDetail(await getApprovalInstanceDetailApi(nextId)); }
      else setRequestDetail(null);
    } finally { setLoadingList(false); setLoadingDetail(false); }
  };

  useEffect(() => {
    if (!open) return;
    setSelectedTaskId(target?.taskId ?? null);
    setSelectedInstanceId(target?.instanceId ?? null);
    setSearchQuery("");
    // Deep-links (from a notification) open straight to the detail; otherwise land on the list.
    setCompactView(target?.taskId || target?.instanceId ? "detail" : "list");
    // setCompactView is owned by the shell and stable; excluding it keeps this to a mount/deep-link reset.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, target?.instanceId, target?.taskId]);

  // Switching the nav section clears the search box so the new list starts unfiltered.
  useEffect(() => {
    setSearchQuery("");
  }, [activeTab]);

  useEffect(() => {
    if (!open) return;
    if (activeTab === "my_tasks") void loadTasks(target?.taskId ?? null, target?.instanceId ?? null);
    else void loadRequests(target?.instanceId ?? null);
    // loadTasks/loadRequests are re-created every render; listing them would refetch on each
    // keystroke. The load is intentionally keyed on "which list is being shown".
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, activeTab]);

  // Auto-select first visible item when sub-filter changes
  const autoSelectTask = (items: ApprovalTaskItem[]) => {
    const first = getId(items[0], "task");
    setSelectedTaskId(first);
    if (first) { setLoadingDetail(true); getMyApprovalTaskDetailApi(first).then(setTaskDetail).finally(() => setLoadingDetail(false)); }
    else setTaskDetail(null);
  };
  const autoSelectRequest = (items: ApprovalInstanceItem[]) => {
    const first = getId(items[0], "instance");
    setSelectedInstanceId(first);
    if (first) { setLoadingDetail(true); getApprovalInstanceDetailApi(first).then(setRequestDetail).finally(() => setLoadingDetail(false)); }
    else setRequestDetail(null);
  };

  // Re-select only when the sub-filter itself changes — following the item lists would fight the
  // user's own selection on every list refresh.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { if (activeTab === "my_tasks") autoSelectTask(filteredTaskItems); }, [taskFilter]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { if (activeTab === "my_requests") autoSelectRequest(filteredRequestItems); }, [requestsFilter]);

  const openTask = async (id: number) => {
    setSelectedTaskId(id); setLoadingDetail(true); setDecisionComment(""); setCompactView("detail");
    try { setTaskDetail(await getMyApprovalTaskDetailApi(id)); } finally { setLoadingDetail(false); }
  };
  const openRequest = async (id: number) => {
    setSelectedInstanceId(id); setLoadingDetail(true); setCompactView("detail");
    try { setRequestDetail(await getApprovalInstanceDetailApi(id)); } finally { setLoadingDetail(false); }
  };

  const runTaskDecision = async (action: "approve" | "reject") => {
    if (!selectedTaskId) return;
    setActionLoading(true);
    const comment =
      decisionComment.trim() ||
      localize(action === "approve" ? "com_approval_action_approve" : "com_approval_action_reject");
    try {
      await decideApprovalTaskApi(selectedTaskId, { action, comment });
      setDecisionComment("");
      await loadTasks(selectedTaskId);
      onPendingCountMaybeChanged?.();
      toast(true);
    }
    catch { toast(false); } finally { setActionLoading(false); }
  };
  const runWithdraw = () => {
    setWithdrawReason("");
    setWithdrawDialogOpen(true);
  };
  const confirmWithdraw = async () => {
    if (!selectedInstanceId) return;
    setWithdrawDialogOpen(false);
    setActionLoading(true);
    try {
      await withdrawApprovalInstanceApi(selectedInstanceId, { reason: withdrawReason.trim() || undefined });
      toast(true);
      const resp = await listMyApprovalRequestsApi();
      setRequestItems(resp.data);
      setRequestsFilter("completed");
      setLoadingDetail(true);
      setRequestDetail(await getApprovalInstanceDetailApi(selectedInstanceId));
      onPendingCountMaybeChanged?.();
    } catch { toast(false); } finally { setActionLoading(false); setLoadingDetail(false); }
  };
  const runRevokeGrant = () => {
    if (!taskDetail?.instance_id) return;
    setRevokeReason("");
    setRevokeDialogOpen(true);
  };
  const confirmRevokeGrant = async () => {
    const instanceId = taskDetail?.instance_id;
    if (!instanceId) return;
    const reason = revokeReason.trim();
    if (!reason) {
      showToast({
        message: localize("com_approval_revoke_reason_required"),
        severity: NotificationSeverity.WARNING,
      });
      return;
    }
    setRevokeDialogOpen(false);
    setActionLoading(true);
    try {
      await revokeMenuAccessGrantApi(instanceId, { reason });
      await loadTasks(selectedTaskId);
      onPendingCountMaybeChanged?.();
      toast(true);
    }
    catch { toast(false); } finally { setActionLoading(false); }
  };

  const isTaskPending = activeTab === "my_tasks" && taskDetail?.status === "pending";
  const isInstancePending = activeTab === "my_requests" && requestDetail?.status === "pending";
  // Only the approver (my_tasks) can revoke a granted menu permission, and only if not already revoked
  const canRevoke =
    activeTab === "my_tasks" &&
    String(taskDetail?.scenario_code ?? "").toLowerCase() === "menu_access_request" &&
    ["approved", "executed"].includes(String(taskDetail?.instance_status ?? "").toLowerCase()) &&
    !taskDetail?.grant_revoked;

  return (
    <>
            {/* Left list — hidden in compact detail view */}
            <div className={cn("flex min-h-0 flex-col border-r border-fill-2 bg-white", compactView === "detail" && "hidden md:flex")}>
              {listHeader}
              {/* 待我处理/已处理 · 审批中/已完成 — design-system Tabs (line type, ink
                  variant: the surrounding column already draws its own edges, so no
                  divider, and an accent here would fight the status badges in the list). */}
              <div className="px-3 pt-3 pb-2">
                <Tabs
                  size="medium"
                  variant="neutral"
                  divider={false}
                  items={
                    activeTab === "my_tasks"
                      ? [
                          { key: "pending_me", label: localize("com_approval_task_filter_pending") },
                          { key: "processed", label: localize("com_approval_task_filter_processed") },
                        ]
                      : [
                          { key: "in_progress", label: localize("com_approval_status_pending") },
                          { key: "completed", label: localize("com_approval_tab_completed") },
                        ]
                  }
                  activeKey={activeTab === "my_tasks" ? taskFilter : requestsFilter}
                  onChange={(key) => {
                    if (activeTab === "my_tasks") setTaskFilter(key as TaskFilter);
                    else setRequestsFilter(key as RequestsFilter);
                  }}
                />
              </div>

              {/* Search box — reuse the app-center search field style (always expanded + clear button) */}
              <div className="px-3 pb-2 pt-1">
                <ExpandableSearchField
                  alwaysExpanded
                  showClearButton
                  value={searchQuery}
                  onChange={setSearchQuery}
                  placeholder={localize("com_approval_search_placeholder")}
                  expandedWidthClassName="w-full"
                />
              </div>

              {loadingList ? (
                <div className="flex flex-1 items-center justify-center text-[14px] text-text-3">{localize("com_approval_loading")}</div>
              ) : (
                <div className="scrollbar-os min-h-0 flex-1 overflow-y-auto px-3 pb-3">
                  {(activeTab === "my_tasks" ? filteredTaskItems : filteredRequestItems).length === 0 ? (
                    <div className="flex h-full items-center justify-center text-[14px] text-text-3">{localize("com_approval_empty_list")}</div>
                  ) : activeTab === "my_tasks"
                    ? filteredTaskItems.map((item) => {
                        const id = getId(item, "task");
                        return (
                          <button key={`t-${id}`} type="button"
                            className={cn("mt-2 w-full rounded-lg border px-4 py-3 text-left transition-colors",
                              selectedTaskId === id ? "border-transparent bg-fill-2" : "border-transparent bg-white hover:bg-fill-1")}
                            onClick={() => id && openTask(id)}>
                            <div className="flex items-start justify-between gap-2">
                              <span className={cn("line-clamp-1 text-[14px] text-text-primary", selectedTaskId === id ? "font-medium" : "font-normal")}>{formatTitle(item.scenario_code, item.business_name, localize)}</span>
                              <div className="flex shrink-0 items-center gap-1">
                                {item.grant_revoked && (
                                  <Tag size="small" className="shrink-0 whitespace-nowrap">
                                    {localize("com_approval_grant_revoked")}
                                  </Tag>
                                )}
                                <StatusBadge status={item.status} instanceStatus={item.instance_status} scope="task" localize={localize} />
                              </div>
                            </div>
                            <div className={cn("mt-1.5 flex items-center justify-between text-[12px]", selectedTaskId === id ? "text-text-3" : "text-text-4")}>
                              <span>{item.applicant_user_name}{item.applicant_department_name ? ` · ${item.applicant_department_name}` : ""}</span>
                              <span>{formatTime(item.create_time)}</span>
                            </div>
                          </button>
                        );
                      })
                    : filteredRequestItems.map((item) => {
                        const id = getId(item, "instance");
                        return (
                          <button key={`r-${id}`} type="button"
                            className={cn("mt-2 w-full rounded-lg border px-4 py-3 text-left transition-colors",
                              selectedInstanceId === id ? "border-transparent bg-fill-2" : "border-transparent bg-white hover:bg-fill-1")}
                            onClick={() => id && openRequest(id)}>
                            <div className="flex items-start justify-between gap-2">
                              <span className={cn("line-clamp-1 text-[14px] text-text-primary", selectedInstanceId === id ? "font-medium" : "font-normal")}>{formatTitle(item.scenario_code, item.business_name, localize)}</span>
                              <div className="flex shrink-0 items-center gap-1">
                                {item.grant_revoked && (
                                  <Tag size="small" className="shrink-0 whitespace-nowrap">
                                    {localize("com_approval_grant_revoked")}
                                  </Tag>
                                )}
                                <StatusBadge status={item.status} scope="instance" localize={localize} />
                              </div>
                            </div>
                            {(item.current_node_name || item.current_approver_names) && (
                              <div className="mt-1.5 flex flex-wrap gap-x-3 text-[12px] text-text-3">
                                {item.current_node_name && <span>{localize("com_approval_current_node_label")}：{item.current_node_name}</span>}
                                {item.current_approver_names && <span>{localize("com_approval_approver_label")}：{item.current_approver_names}</span>}
                              </div>
                            )}
                          </button>
                        );
                      })}
                </div>
              )}
            </div>

            {/* Right detail — hidden in compact list view (back control lives in the header) */}
            <div className={cn("flex min-h-0 flex-col", compactView === "list" && "hidden md:flex")}>
              <div className="scrollbar-os min-h-0 flex-1 overflow-y-auto px-5 pb-3">
                {loadingDetail ? (
                  <div className="flex h-full items-center justify-center text-[14px] text-text-3">{localize("com_approval_loading")}</div>
                ) : activeTab === "my_tasks" && taskDetail ? (
                  <TaskDetailPanel detail={taskDetail} localize={localize} onBack={() => setCompactView("list")} />
                ) : activeTab === "my_requests" && requestDetail ? (
                  <RequestDetailPanel detail={requestDetail} localize={localize} onBack={() => setCompactView("list")} />
                ) : (
                  <div className="flex h-full items-center justify-center text-[14px] text-text-3">{localize("com_approval_empty_detail")}</div>
                )}
              </div>

              {/* Fixed footer buttons */}
              {(isTaskPending || isInstancePending || canRevoke) && (
                <div className="flex flex-col gap-4 border-t border-fill-2 px-5 py-4">
                  {isTaskPending && (
                    <textarea
                      value={decisionComment}
                      onChange={(e) => setDecisionComment(e.target.value)}
                      placeholder={localize("com_approval_decision_comment_placeholder")}
                      rows={2}
                      className="w-full resize-none rounded-lg border border-border-base px-3 py-2 text-[13px] text-text-primary placeholder:text-text-4 outline-none transition-[border-color,box-shadow] focus:border-[#DDDDDD] focus:shadow-[0_0_0_2px_#F1F5F9]"
                    />
                  )}
                  <div className="flex items-center justify-end gap-3">
                  {isTaskPending && (
                    <>
                      <button type="button" disabled={actionLoading}
                        className="inline-flex h-8 flex-1 items-center justify-center rounded-md border border-[#f53f3f] px-4 text-[14px] font-normal text-[#f53f3f] hover:bg-[#fff2f0] disabled:opacity-60 md:flex-none"
                        onClick={() => runTaskDecision("reject")}>
                        {localize("com_approval_action_reject")}
                      </button>
                      <button type="button" disabled={actionLoading}
                        className="inline-flex h-8 flex-1 items-center justify-center rounded-md bg-blue-500 px-4 text-[14px] font-normal text-white hover:bg-blue-600 disabled:opacity-60 md:flex-none btn-brand-primary"
                        onClick={() => runTaskDecision("approve")}>
                        {localize("com_approval_action_approve")}
                      </button>
                    </>
                  )}
                  {isInstancePending && (
                    <button type="button" disabled={actionLoading}
                      className="inline-flex h-8 flex-1 items-center justify-center rounded-md border border-blue-500 px-4 text-[14px] font-normal text-blue-500 hover:bg-blue-500/[0.06] disabled:opacity-60 md:flex-none"
                      onClick={runWithdraw}>
                      {localize("com_approval_action_withdraw")}
                    </button>
                  )}
                  {canRevoke && (
                    <button type="button" disabled={actionLoading}
                      className="inline-flex h-8 flex-1 items-center justify-center rounded-md border border-[#ff7d00] px-4 text-[14px] font-normal text-[#ff7d00] hover:bg-[#fff7e8] disabled:opacity-60 md:flex-none"
                      onClick={runRevokeGrant}>
                      {localize("com_approval_action_revoke_grant")}
                    </button>
                  )}
                  </div>
                </div>
              )}
            </div>
      <Dialog open={revokeDialogOpen} onOpenChange={setRevokeDialogOpen}>
        <DialogContent close={false} overlayClassName="z-[150]" className="z-[200] max-w-[400px] rounded-lg">
          <div className="text-[16px] font-semibold text-text-primary">{localize("com_approval_revoke_dialog_title")}</div>
          <textarea
            rows={4}
            value={revokeReason}
            onChange={(e) => setRevokeReason(e.target.value)}
            maxLength={500}
            placeholder={localize("com_approval_revoke_reason_placeholder")}
            className="mt-2 w-full resize-none rounded-lg border border-border-base px-3 py-2 text-[14px] text-text-primary placeholder:text-text-4 outline-none focus:border-blue-500"
          />
          <div className="mt-4 flex justify-end gap-3">
            <button type="button"
              className="rounded-lg border border-border-base px-4 py-2 text-[14px] text-text-2 hover:bg-fill-1"
              onClick={() => setRevokeDialogOpen(false)}>
              {localize("com_ui_cancel")}
            </button>
            <button type="button"
              disabled={!revokeReason.trim()}
              className="rounded-lg border border-[#ff7d00] px-4 py-2 text-[14px] text-[#ff7d00] hover:bg-[#fff7e8] disabled:opacity-60"
              onClick={confirmRevokeGrant}>
              {localize("com_approval_action_revoke_grant")}
            </button>
          </div>
        </DialogContent>
      </Dialog>
      <Dialog open={withdrawDialogOpen} onOpenChange={setWithdrawDialogOpen}>
        <DialogContent close={false} overlayClassName="z-[150]" className="z-[200] max-w-[400px] rounded-lg">
          <div className="text-[16px] font-semibold text-text-primary">{localize("com_approval_withdraw_dialog_title")}</div>
          <textarea
            rows={4}
            value={withdrawReason}
            onChange={(e) => setWithdrawReason(e.target.value)}
            maxLength={500}
            placeholder={localize("com_approval_withdraw_reason_placeholder")}
            className="mt-2 w-full resize-none rounded-lg border border-border-base px-3 py-2 text-[14px] text-text-primary placeholder:text-text-4 outline-none focus:border-blue-500"
          />
          <div className="mt-4 flex justify-end gap-3">
            <button type="button"
              className="rounded-lg border border-border-base px-4 py-2 text-[14px] text-text-2 hover:bg-fill-1"
              onClick={() => setWithdrawDialogOpen(false)}>
              {localize("com_ui_cancel")}
            </button>
            <button type="button"
              className="rounded-lg border border-blue-500 px-4 py-2 text-[14px] text-blue-500 hover:bg-blue-500/[0.06]"
              onClick={confirmWithdraw}>
              {localize("com_approval_action_withdraw")}
            </button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
