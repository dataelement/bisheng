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
import { Dialog, DialogContent } from "../ui/Dialog";

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

type TaskFilter = "pending_me" | "processed";
type RequestsFilter = "in_progress" | "completed";
const IN_PROGRESS_STATUSES = new Set(["pending", "exception", "execute_failed"]);

function getId(item: { task_id?: number; id?: number; instance_id?: number } | null | undefined, type: "task" | "instance"): number | null {
  const raw = type === "task" ? (item?.task_id ?? item?.id) : ((item as any)?.instance_id ?? item?.id);
  const n = Number(raw);
  return Number.isFinite(n) ? n : null;
}

function formatSerialNo(instanceId: number, ts?: string | null): string {
  const d = ts ? new Date(ts) : new Date();
  return `SP${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, "0")}${String(d.getDate()).padStart(2, "0")}${String(instanceId).padStart(4, "0")}`;
}

function formatTime(ts?: string | Date | null): string {
  if (!ts) return "--";
  const d = new Date(ts as string);
  if (Number.isNaN(d.getTime())) return String(ts);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function StatusBadge({ status, instanceStatus, localize }: { status?: string | null; instanceStatus?: string | null; localize: ReturnType<typeof useLocalize> }) {
  const s = String(status || "").toLowerCase();
  const is = String(instanceStatus || "").toLowerCase();
  // Combine task status and instance status for display
  const effective = s === "approved" && is === "execute_failed" ? "execute_failed" : s;
  const MAP: Record<string, { text: string; cls: string }> = {
    pending:        { text: localize("com_approval_task_badge_pending"),    cls: "bg-[#e8f3ff] text-[#165dff]" },
    approved:       { text: localize("com_approval_task_badge_approved"),   cls: "bg-[#e8ffea] text-[#00b42a]" },
    rejected:       { text: localize("com_approval_task_badge_rejected"),   cls: "bg-[#fff2f0] text-[#f53f3f]" },
    cancelled:      { text: localize("com_approval_status_cancelled"),      cls: "bg-[#f7f8fa] text-[#86909c]" },
    skipped:        { text: localize("com_approval_status_skipped"),        cls: "bg-[#f7f8fa] text-[#86909c]" },
    execute_failed: { text: localize("com_approval_badge_exception"),       cls: "bg-[#fff7e8] text-[#ff7d00]" },
    exception:      { text: localize("com_approval_badge_exception"),       cls: "bg-[#fff7e8] text-[#ff7d00]" },
    // for instance status in my_requests
    withdrawn:      { text: localize("com_approval_status_withdrawn"),      cls: "bg-[#f7f8fa] text-[#86909c]" },
    executed:       { text: localize("com_approval_badge_approved"),        cls: "bg-[#e8ffea] text-[#00b42a]" },
  };
  const { text, cls } = MAP[effective] ?? MAP[s] ?? { text: status ?? "--", cls: "bg-[#f7f8fa] text-[#86909c]" };
  return <span className={cn("shrink-0 rounded-full px-2 py-0.5 text-[12px] font-medium", cls)}>{text}</span>;
}

function TimelineStep({ action, operatorName, createTime, detail, localize, isLast }: {
  action?: string; operatorName?: string | null; createTime?: string | null;
  detail?: Record<string, any> | null; localize: ReturnType<typeof useLocalize>; isLast?: boolean;
}) {
  const a = String(action || "").toLowerCase();
  const dotCls = a === "approved" ? "bg-[#00b42a] text-white" : a === "rejected" ? "bg-[#f53f3f] text-white" :
    a === "withdrawn" ? "bg-[#86909c] text-white" : "bg-[#165dff] text-white";
  const icon = a === "approved" ? "✓" : a === "rejected" ? "✗" : "●";
  const title = a === "submitted" ? localize("com_approval_step_submitted") :
    a === "resubmitted" ? localize("com_approval_action_resubmitted") :
    a === "approved" ? localize("com_approval_action_approved") :
    a === "rejected" ? localize("com_approval_action_rejected") :
    a === "withdrawn" ? localize("com_approval_action_withdrawn") :
    (localize(`com_approval_action_${a}` as any, { defaultValue: a }) as string);
  const desc = a === "submitted" ? localize("com_approval_step_submitted_desc") : operatorName ?? null;
  const comment = detail?.comment || detail?.reason;
  return (
    <div className="flex gap-3">
      <div className="flex flex-col items-center">
        <span className={cn("flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px]", dotCls)}>{icon}</span>
        {!isLast && <span className="mt-1 w-px flex-1 bg-[#e5e6eb]" />}
      </div>
      <div className={cn("min-w-0 pt-0.5", isLast ? "pb-1" : "pb-4")}>
        <div className="text-[14px] font-medium text-[#1d2129]">{title}</div>
        {desc && <div className="mt-0.5 text-[12px] text-[#86909c]">{desc}</div>}
        {comment && <div className="mt-1 rounded-lg bg-[#f7f8fa] px-3 py-2 text-[12px] text-[#4e5969] break-all">{comment}</div>}
        <div className="mt-1 text-[11px] text-[#c9cdd4]">{formatTime(createTime)}</div>
      </div>
    </div>
  );
}

function PendingTimelineStep({ nodeName }: { nodeName?: string | null }) {
  return (
    <div className="flex gap-3">
      <div className="flex flex-col items-center">
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[#165dff] text-[11px] text-white">●</span>
      </div>
      <div className="pt-0.5">
        <div className="text-[14px] font-medium text-[#1d2129]">{nodeName || "--"}</div>
      </div>
    </div>
  );
}

function formatTitle(
  scenarioCode: string | undefined,
  businessName: string | undefined | null,
  localize: ReturnType<typeof useLocalize>,
): string {
  if (!businessName) return "--";
  if (scenarioCode === "menu_access_request") {
    return localize("com_approval_menu_access_title" as any, { menuName: businessName, defaultValue: `申请访问${businessName}菜单` }) as string;
  }
  return businessName;
}

const DETAIL_INTERNAL_KEYS = new Set(["menu_key", "space_id", "channel_id", "applicant_user_id", "applicant_user_name"]);

function localizeFieldKey(key: string, localize: ReturnType<typeof useLocalize>): string {
  const map: Record<string, string> = {
    menu_key:      localize("com_approval_field_menu_key" as any),
    menu_name:     localize("com_approval_field_menu_name" as any),
    reason:        localize("com_approval_field_reason" as any),
    space_type:    localize("com_approval_field_space_type" as any),
    space_name:    localize("com_approval_field_space_name" as any),
    channel_id:    localize("com_approval_field_channel_id" as any),
    channel_name:  localize("com_approval_field_channel_name" as any),
    space_id:      localize("com_approval_field_space_id" as any),
  };
  return map[key] ?? key;
}

function InfoGrid({ rows }: { rows: [string, string][] }) {
  return (
    <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-[#f2f3f5] bg-[#f2f3f5]">
      {rows.map(([label, value]) => (
        <div key={label} className="bg-white px-4 py-3">
          <div className="text-[12px] text-[#86909c]">{label}</div>
          <div className="mt-1 text-[14px] font-medium text-[#1d2129] break-all">{value || "--"}</div>
        </div>
      ))}
    </div>
  );
}

export function ApprovalCenterDialog({ open, onOpenChange, target }: ApprovalCenterDialogProps) {
  const localize = useLocalize();
  const { showToast } = useToastContext();

  const [activeTab, setActiveTab] = useState<ApprovalCenterTab>(target?.tab ?? "my_tasks");
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

  const loadTasks = async (preferredId?: number | null) => {
    setLoadingList(true);
    try {
      const resp = await listMyApprovalTasksApi();
      setTaskItems(resp.data);
      const allIds = new Set(resp.data.map((t) => getId(t, "task")));
      const validPreferred = preferredId && allIds.has(preferredId) ? preferredId : null;
      const visibleItems = taskFilter === "pending_me"
        ? resp.data.filter((t) => t.status === "pending")
        : resp.data.filter((t) => t.status !== "pending");
      const nextId = validPreferred ?? getId(visibleItems[0], "task");
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
      const allIds = new Set(resp.data.map((i) => getId(i, "instance")));
      const validPreferred = preferredId && allIds.has(preferredId) ? preferredId : null;
      const visibleItems = requestsFilter === "in_progress"
        ? resp.data.filter((i) => IN_PROGRESS_STATUSES.has(i.status ?? ""))
        : resp.data.filter((i) => !IN_PROGRESS_STATUSES.has(i.status ?? ""));
      const nextId = validPreferred ?? getId(visibleItems[0], "instance");
      setSelectedInstanceId(nextId);
      if (nextId) { setLoadingDetail(true); setRequestDetail(await getApprovalInstanceDetailApi(nextId)); }
      else setRequestDetail(null);
    } finally { setLoadingList(false); setLoadingDetail(false); }
  };

  useEffect(() => {
    if (!open) return;
    setActiveTab(target?.tab ?? "my_tasks");
    setSelectedTaskId(target?.taskId ?? null);
    setSelectedInstanceId(target?.instanceId ?? null);
    setSearchQuery("");
  }, [open, target?.instanceId, target?.tab, target?.taskId]);

  useEffect(() => {
    if (!open) return;
    if (activeTab === "my_tasks") void loadTasks(target?.taskId ?? null);
    else void loadRequests(target?.instanceId ?? null);
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

  useEffect(() => { if (activeTab === "my_tasks") autoSelectTask(filteredTaskItems); }, [taskFilter]);
  useEffect(() => { if (activeTab === "my_requests") autoSelectRequest(filteredRequestItems); }, [requestsFilter]);

  const openTask = async (id: number) => {
    setSelectedTaskId(id); setLoadingDetail(true); setDecisionComment("");
    try { setTaskDetail(await getMyApprovalTaskDetailApi(id)); } finally { setLoadingDetail(false); }
  };
  const openRequest = async (id: number) => {
    setSelectedInstanceId(id); setLoadingDetail(true);
    try { setRequestDetail(await getApprovalInstanceDetailApi(id)); } finally { setLoadingDetail(false); }
  };

  const runTaskDecision = async (action: "approve" | "reject") => {
    if (!selectedTaskId) return;
    setActionLoading(true);
    const comment = decisionComment.trim() || (action === "approve" ? "同意" : "驳回");
    try { await decideApprovalTaskApi(selectedTaskId, { action, comment }); setDecisionComment(""); await loadTasks(selectedTaskId); toast(true); }
    catch { toast(false); } finally { setActionLoading(false); }
  };
  const runWithdraw = async () => {
    if (!selectedInstanceId) return;
    setActionLoading(true);
    try {
      await withdrawApprovalInstanceApi(selectedInstanceId, {});
      toast(true);
      const resp = await listMyApprovalRequestsApi();
      setRequestItems(resp.data);
      setRequestsFilter("completed");
      setLoadingDetail(true);
      setRequestDetail(await getApprovalInstanceDetailApi(selectedInstanceId));
    } catch { toast(false); } finally { setActionLoading(false); setLoadingDetail(false); }
  };
  const runResubmit = async () => {
    if (!selectedInstanceId) return;
    setActionLoading(true);
    try { await resubmitApprovalInstanceApi(selectedInstanceId, {}); await loadRequests(selectedInstanceId); toast(true); }
    catch { toast(false); } finally { setActionLoading(false); }
  };
  const runRevokeGrant = async () => {
    // Approver revokes from my_tasks using the task's instance_id
    const instanceId = taskDetail?.instance_id;
    if (!instanceId) return;
    setActionLoading(true);
    try { await revokeMenuAccessGrantApi(instanceId, {}); await loadTasks(selectedTaskId); toast(true); }
    catch { toast(false); } finally { setActionLoading(false); }
  };

  const isTaskPending = activeTab === "my_tasks" && taskDetail?.status === "pending";
  const isInstancePending = activeTab === "my_requests" && requestDetail?.status === "pending";
  const canResubmit = activeTab === "my_requests" && requestDetail?.status === "rejected";
  // Only the approver (my_tasks) can revoke a granted menu permission
  const canRevoke =
    activeTab === "my_tasks" &&
    String(taskDetail?.scenario_code ?? "").toLowerCase() === "menu_access_request" &&
    ["approved", "executed"].includes(String(taskDetail?.instance_status ?? "").toLowerCase());

  const dialogTitle = activeTab === "my_tasks" ? localize("com_approval_my_approval") : localize("com_approval_my_requests");
  const dialogSubtitle = activeTab === "my_tasks" ? localize("com_approval_my_approval_desc") : localize("com_approval_my_requests_desc");

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="h-[80vh] max-h-[820px] w-[calc(100vw-64px)] max-w-[1080px] rounded-2xl p-0">
        <div className="flex h-full flex-col overflow-hidden rounded-2xl bg-white">
          {/* Header */}
          <div className="border-b border-[#f2f3f5] px-6 py-4">
            <h2 className="text-[18px] font-semibold text-[#1d2129]">{dialogTitle}</h2>
            <p className="mt-0.5 text-[13px] text-[#86909c]">{dialogSubtitle}</p>
          </div>

          {/* Top tabs */}
          <div className="flex items-center justify-between border-b border-[#f2f3f5] px-6 py-2">
            <div className="flex gap-1">
              {(["my_tasks", "my_requests"] as ApprovalCenterTab[]).map((tab) => (
                <button key={tab} type="button"
                  className={cn("rounded-lg px-4 py-2 text-[14px] transition-colors",
                    activeTab === tab ? "bg-[#e8f3ff] text-[#165dff] font-medium" : "text-[#4e5969] hover:bg-[#f7f8fa]")}
                  onClick={() => { setActiveTab(tab); setSearchQuery(""); }}>
                  {tab === "my_tasks" ? localize("com_approval_my_approval") : localize("com_approval_my_requests")}
                </button>
              ))}
            </div>
            <div className="flex items-center gap-1.5 rounded-lg border border-[#e5e6eb] px-3 py-1.5 text-[13px] text-[#c9cdd4] focus-within:border-[#165dff]">
              <span>⌕</span>
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder={localize("com_approval_search_placeholder")}
                className="w-40 bg-transparent text-[#1d2129] placeholder:text-[#c9cdd4] outline-none"
              />
            </div>
          </div>

          <div className="grid min-h-0 flex-1 grid-cols-[320px_minmax(0,1fr)]">
            {/* Left list */}
            <div className="flex min-h-0 flex-col border-r border-[#f2f3f5] bg-[#fafbfc]">
              <div className="flex gap-1 px-3 pt-3 pb-1">
                {activeTab === "my_tasks"
                  ? (["pending_me", "processed"] as TaskFilter[]).map((f) => (
                      <button key={f} type="button"
                        className={cn("rounded-md px-3 py-1 text-[13px] transition-colors",
                          taskFilter === f ? "bg-[#165dff] text-white" : "text-[#4e5969] hover:bg-[#edf0f5]")}
                        onClick={() => setTaskFilter(f)}>
                        {f === "pending_me" ? localize("com_approval_task_filter_pending") : localize("com_approval_task_filter_processed")}
                      </button>
                    ))
                  : (["in_progress", "completed"] as RequestsFilter[]).map((f) => (
                      <button key={f} type="button"
                        className={cn("rounded-md px-3 py-1 text-[13px] transition-colors",
                          requestsFilter === f ? "bg-[#165dff] text-white" : "text-[#4e5969] hover:bg-[#edf0f5]")}
                        onClick={() => setRequestsFilter(f)}>
                        {f === "in_progress" ? localize("com_approval_status_pending") : localize("com_approval_tab_completed")}
                      </button>
                    ))}
              </div>

              {loadingList ? (
                <div className="flex flex-1 items-center justify-center text-[14px] text-[#86909c]">{localize("com_approval_loading")}</div>
              ) : (
                <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-3">
                  {(activeTab === "my_tasks" ? filteredTaskItems : filteredRequestItems).length === 0 ? (
                    <div className="flex h-full items-center justify-center text-[14px] text-[#86909c]">{localize("com_approval_empty_list")}</div>
                  ) : activeTab === "my_tasks"
                    ? filteredTaskItems.map((item) => {
                        const id = getId(item, "task");
                        return (
                          <button key={`t-${id}`} type="button"
                            className={cn("mt-2 w-full rounded-xl border px-4 py-3 text-left transition-colors",
                              selectedTaskId === id ? "border-[#165dff] bg-white shadow-[0_2px_12px_rgba(22,93,255,0.08)]" : "border-transparent bg-white hover:border-[#d9e3f0]")}
                            onClick={() => id && openTask(id)}>
                            <div className="flex items-start justify-between gap-2">
                              <span className="line-clamp-1 text-[14px] font-medium text-[#1d2129]">{formatTitle(item.scenario_code, item.business_name, localize)}</span>
                              <StatusBadge status={item.status} instanceStatus={item.instance_status} localize={localize} />
                            </div>
                            {item.current_node_name && (
                              <div className="mt-1.5 text-[12px] text-[#86909c]">
                                {localize("com_approval_current_node_label")}：{item.current_node_name}
                              </div>
                            )}
                            <div className="mt-1.5 flex items-center justify-between text-[12px] text-[#c9cdd4]">
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
                            className={cn("mt-2 w-full rounded-xl border px-4 py-3 text-left transition-colors",
                              selectedInstanceId === id ? "border-[#165dff] bg-white shadow-[0_2px_12px_rgba(22,93,255,0.08)]" : "border-transparent bg-white hover:border-[#d9e3f0]")}
                            onClick={() => id && openRequest(id)}>
                            <div className="flex items-start justify-between gap-2">
                              <span className="line-clamp-1 text-[14px] font-medium text-[#1d2129]">{formatTitle(item.scenario_code, item.business_name, localize)}</span>
                              <div className="flex shrink-0 items-center gap-1">
                                {item.grant_revoked && (
                                  <span className="rounded-full bg-[#f7f8fa] px-2 py-0.5 text-[12px] font-medium text-[#86909c]">
                                    {localize("com_approval_grant_revoked")}
                                  </span>
                                )}
                                <StatusBadge status={item.status} localize={localize} />
                              </div>
                            </div>
                            {(item.current_node_name || item.current_approver_names) && (
                              <div className="mt-1.5 flex flex-wrap gap-x-3 text-[12px] text-[#86909c]">
                                {item.current_node_name && <span>{localize("com_approval_current_node_label")}：{item.current_node_name}</span>}
                                {item.current_approver_names && <span>{localize("com_approval_approver_label")}：{item.current_approver_names}</span>}
                              </div>
                            )}
                            <div className="mt-1.5 flex items-center justify-between text-[12px] text-[#c9cdd4]">
                              <span>{item.applicant_user_name}{item.applicant_department_name ? ` · ${item.applicant_department_name}` : ""}</span>
                              <span>{formatTime(item.create_time)}</span>
                            </div>
                          </button>
                        );
                      })}
                </div>
              )}
            </div>

            {/* Right detail */}
            <div className="flex min-h-0 flex-col">
              <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
                {loadingDetail ? (
                  <div className="flex h-full items-center justify-center text-[14px] text-[#86909c]">{localize("com_approval_loading")}</div>
                ) : activeTab === "my_tasks" && taskDetail ? (
                  <TaskDetailPanel detail={taskDetail} localize={localize} />
                ) : activeTab === "my_requests" && requestDetail ? (
                  <RequestDetailPanel detail={requestDetail} localize={localize} />
                ) : (
                  <div className="flex h-full items-center justify-center text-[14px] text-[#86909c]">{localize("com_approval_empty_detail")}</div>
                )}
              </div>

              {/* Fixed footer buttons */}
              {(isTaskPending || isInstancePending || canResubmit || canRevoke) && (
                <div className="flex flex-col gap-3 border-t border-[#f2f3f5] px-6 py-4">
                  {isTaskPending && (
                    <textarea
                      value={decisionComment}
                      onChange={(e) => setDecisionComment(e.target.value)}
                      placeholder={localize("com_approval_decision_comment_placeholder")}
                      rows={2}
                      className="w-full resize-none rounded-lg border border-[#e5e6eb] px-3 py-2 text-[13px] text-[#1d2129] placeholder:text-[#c9cdd4] outline-none focus:border-[#165dff]"
                    />
                  )}
                  <div className="flex items-center justify-end gap-3">
                  <button type="button"
                    className="rounded-lg border border-[#e5e6eb] px-4 py-2 text-[14px] text-[#4e5969] hover:bg-[#f7f8fa]"
                    onClick={() => onOpenChange(false)}>
                    {localize("com_ui_close")}
                  </button>
                  {isTaskPending && (
                    <>
                      <button type="button" disabled={actionLoading}
                        className="rounded-lg border border-[#f53f3f] px-4 py-2 text-[14px] text-[#f53f3f] hover:bg-[#fff2f0] disabled:opacity-60"
                        onClick={() => runTaskDecision("reject")}>
                        {localize("com_approval_action_reject")}
                      </button>
                      <button type="button" disabled={actionLoading}
                        className="rounded-lg bg-[#165dff] px-5 py-2 text-[14px] text-white hover:bg-[#1350e8] disabled:opacity-60"
                        onClick={() => runTaskDecision("approve")}>
                        {localize("com_approval_action_approve")}
                      </button>
                    </>
                  )}
                  {isInstancePending && (
                    <button type="button" disabled={actionLoading}
                      className="rounded-lg border border-[#165dff] px-4 py-2 text-[14px] text-[#165dff] hover:bg-[#f2f7ff] disabled:opacity-60"
                      onClick={runWithdraw}>
                      {localize("com_approval_action_withdraw")}
                    </button>
                  )}
                  {canResubmit && (
                    <button type="button" disabled={actionLoading}
                      className="rounded-lg bg-[#722ed1] px-4 py-2 text-[14px] text-white hover:bg-[#6327b3] disabled:opacity-60"
                      onClick={runResubmit}>
                      {localize("com_approval_action_resubmit")}
                    </button>
                  )}
                  {canRevoke && (
                    <button type="button" disabled={actionLoading}
                      className="rounded-lg border border-[#ff7d00] px-4 py-2 text-[14px] text-[#ff7d00] hover:bg-[#fff7e8] disabled:opacity-60"
                      onClick={runRevokeGrant}>
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

function DetailHeader({ title, status, instanceStatus, serialNo, scenarioName, createTime, localize }: {
  title?: string; status?: string; instanceStatus?: string; serialNo: string; scenarioName?: string; createTime?: string | null; localize: ReturnType<typeof useLocalize>;
}) {
  return (
    <div className="mb-5">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 text-[#86909c]">📄</span>
        <h3 className="flex-1 text-[18px] font-semibold text-[#1d2129] leading-snug">{title || "--"}</h3>
        <StatusBadge status={status} instanceStatus={instanceStatus} localize={localize} />
      </div>
      <p className="mt-1.5 text-[13px] text-[#86909c] pl-6">
        {serialNo} · {scenarioName || "--"} · {formatTime(createTime)}
      </p>
    </div>
  );
}

function TaskDetailPanel({ detail, localize }: { detail: ApprovalTaskDetail; localize: ReturnType<typeof useLocalize> }) {
  const instanceId = detail.instance_id;
  const serialNo = instanceId ? formatSerialNo(instanceId, detail.create_time) : "--";

  const basicRows: [string, string][] = [
    [localize("com_approval_field_serial_no"),      serialNo],
    [localize("com_approval_field_scenario_type"),  detail.scenario_name || detail.scenario_code || "--"],
    [localize("com_approval_field_business_target"),detail.business_name || "--"],
    [localize("com_approval_field_applicant"),       detail.applicant_user_name || "--"],
    [localize("com_approval_field_department"),      detail.applicant_department_name || "--"],
    [localize("com_approval_field_apply_time"),      formatTime(detail.create_time)],
    [localize("com_approval_status_label").replace("：", ""), localize(`com_approval_status_${detail.instance_status ?? detail.status}` as any, { defaultValue: detail.instance_status || detail.status || "--" }) as string],
  ];

  const detailEntries = Object.entries(detail.detail_snapshot ?? detail.payload_snapshot ?? {}).filter(
    ([k, v]) => !DETAIL_INTERNAL_KEYS.has(k) && v !== undefined && v !== null && v !== "",
  );
  const showContent = detailEntries.length > 0;

  return (
    <div className="space-y-5">
      <DetailHeader title={formatTitle(detail.scenario_code, detail.business_name, localize)} status={detail.status} instanceStatus={detail.instance_status}
        serialNo={serialNo} scenarioName={detail.scenario_name || detail.scenario_code} createTime={detail.create_time} localize={localize} />

      <div>
        <div className="mb-2 text-[14px] font-medium text-[#1d2129]">{localize("com_approval_section_basic_info")}</div>
        <InfoGrid rows={basicRows} />
      </div>

      {showContent && (
        <div>
          <div className="mb-2 text-[14px] font-medium text-[#1d2129]">{localize("com_approval_section_business_content")}</div>
          <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-[#f2f3f5] bg-[#f2f3f5]">
            {detailEntries.map(([k, v]) => (
              <div key={k} className="bg-white px-4 py-3">
                <div className="text-[12px] text-[#86909c]">{localizeFieldKey(k, localize)}</div>
                <div className="mt-1 text-[14px] text-[#1d2129] break-all">{Array.isArray(v) ? v.join(", ") : String(v)}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {detail.reason && (
        <div>
          <div className="mb-2 text-[14px] font-medium text-[#1d2129]">{localize("com_approval_section_apply_reason")}</div>
          <div className="rounded-xl bg-[#fafbfc] p-4 text-[14px] text-[#4e5969] break-all">{detail.reason}</div>
        </div>
      )}

      {(detail.action_logs && detail.action_logs.length > 0) || detail.current_node_name ? (
        <div>
          <div className="mb-3 flex items-center gap-1.5 text-[14px] font-medium text-[#1d2129]">
            <span className="text-[16px]">⊙</span>
            {localize("com_approval_progress_section")}
          </div>
          {(detail.action_logs || []).map((log, i) => (
            <TimelineStep key={log.id ?? i} action={log.action} operatorName={log.operator_user_name}
              createTime={log.create_time} detail={log.detail} localize={localize} />
          ))}
          {detail.status === "pending" && detail.current_node_name && (
            <PendingTimelineStep nodeName={detail.current_node_name} />
          )}
        </div>
      ) : null}
    </div>
  );
}

function RequestDetailPanel({ detail, localize }: { detail: ApprovalInstanceDetail; localize: ReturnType<typeof useLocalize> }) {
  const id = detail.instance_id ?? detail.id;
  const serialNo = id ? formatSerialNo(Number(id), detail.create_time) : "--";

  const isTerminal = ["executed", "rejected", "withdrawn", "cancelled"].includes(detail.status ?? "");
  const basicRows: [string, string][] = [
    [localize("com_approval_field_serial_no"),      serialNo],
    [localize("com_approval_field_scenario_type"),  detail.scenario_name || detail.scenario_code || "--"],
    [localize("com_approval_field_business_target"),detail.business_name || "--"],
    [localize("com_approval_field_applicant"),       detail.applicant_user_name || "--"],
    [localize("com_approval_field_department"),      detail.applicant_department_name || "--"],
    [localize("com_approval_field_apply_time"),      formatTime(detail.create_time)],
    ...(!isTerminal ? [[localize("com_approval_field_current_approver"), detail.current_approver_names || "--"] as [string, string]] : []),
    [localize("com_approval_status_label").replace("：", ""), localize(`com_approval_status_${detail.status}` as any, { defaultValue: detail.status ?? "--" }) as string],
  ];

  const detailEntries = Object.entries(detail.detail_snapshot ?? {}).filter(
    ([k, v]) => !DETAIL_INTERNAL_KEYS.has(k) && v !== undefined && v !== null && v !== "",
  );

  return (
    <div className="space-y-5">
      <DetailHeader title={formatTitle(detail.scenario_code, detail.business_name, localize)} status={detail.status} serialNo={serialNo}
        scenarioName={detail.scenario_name || detail.scenario_code} createTime={detail.create_time} localize={localize} />

      <div>
        <div className="mb-2 text-[14px] font-medium text-[#1d2129]">{localize("com_approval_section_basic_info")}</div>
        <InfoGrid rows={basicRows} />
      </div>

      {detailEntries.length > 0 && (
        <div>
          <div className="mb-2 text-[14px] font-medium text-[#1d2129]">{localize("com_approval_section_business_content")}</div>
          <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-[#f2f3f5] bg-[#f2f3f5]">
            {detailEntries.map(([k, v]) => (
              <div key={k} className="bg-white px-4 py-3">
                <div className="text-[12px] text-[#86909c]">{localizeFieldKey(k, localize)}</div>
                <div className="mt-1 text-[14px] text-[#1d2129] break-all">{Array.isArray(v) ? v.join(", ") : String(v)}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {detail.reason && (
        <div>
          <div className="mb-2 text-[14px] font-medium text-[#1d2129]">{localize("com_approval_section_apply_reason")}</div>
          <div className="rounded-xl bg-[#fafbfc] p-4 text-[14px] text-[#4e5969] break-all">{detail.reason}</div>
        </div>
      )}

      {((detail.action_logs && detail.action_logs.length > 0) || (detail.tasks && detail.tasks.length > 0)) && (
        <div>
          <div className="mb-3 flex items-center gap-1.5 text-[14px] font-medium text-[#1d2129]">
            <span className="text-[16px]">⊙</span>
            {localize("com_approval_progress_section")}
          </div>
          {/* submitted / resubmitted logs first */}
          {(detail.action_logs || [])
            .filter((l) => l.action === "submitted" || l.action === "resubmitted")
            .map((log, i) => (
              <TimelineStep key={log.id ?? `s${i}`} action={log.action} operatorName={log.operator_user_name}
                createTime={log.create_time} detail={log.detail} localize={localize} isLast={false} />
            ))}
          {/* all flow nodes — use flow_nodes as skeleton; fall back to tasks */}
          {(() => {
            const nodes = detail.flow_nodes && detail.flow_nodes.length > 0
              ? [...detail.flow_nodes].sort((a, b) => (a.node_order ?? 0) - (b.node_order ?? 0))
              : [...(detail.tasks || [])].sort((a, b) => (a.node_order ?? 0) - (b.node_order ?? 0));
            const hasTrailingLogs = (detail.action_logs || []).some(
              (l) => l.action !== "submitted" && l.action !== "resubmitted"
            );
            return nodes.map((node: any, i) => {
              // Collect all tasks for this node (multi-approver nodes have multiple tasks)
              const matchedTasks = (detail.tasks || []).filter(
                (t) => t.node_order === node.node_order || t.node_name === node.node_name
              );
              const isNotStarted = matchedTasks.length === 0 && !node.task_id;
              // Aggregate node status: rejected > approved > pending > others
              const aggStatus = matchedTasks.length === 0
                ? (node.task_id ? (node.status ?? "pending") : "not_started")
                : matchedTasks.some((t) => t.status === "rejected") ? "rejected"
                : matchedTasks.some((t) => t.status === "approved") ? "approved"
                : matchedTasks.some((t) => t.status === "pending") ? "pending"
                : (matchedTasks[0]?.status ?? "pending");
              const s = aggStatus.toLowerCase();
              const dotColor = isNotStarted ? "bg-[#e5e6eb]" :
                s === "approved" ? "bg-[#00b42a]" : s === "rejected" ? "bg-[#f53f3f]" :
                (s === "cancelled" || s === "skipped") ? "bg-[#c9cdd4]" : "bg-[#165dff]";
              const isLast = i === nodes.length - 1 && !hasTrailingLogs;
              const nodeBadgeMap: Record<string, { text: string; cls: string }> = {
                approved:  { text: localize("com_approval_status_approved"),  cls: "bg-[#e8ffea] text-[#00b42a]" },
                rejected:  { text: localize("com_approval_status_rejected"),  cls: "bg-[#fff2f0] text-[#f53f3f]" },
                pending:   { text: localize("com_approval_status_pending"),   cls: "bg-[#e8f3ff] text-[#165dff]" },
                skipped:   { text: localize("com_approval_status_skipped"),   cls: "bg-[#f7f8fa] text-[#86909c]" },
                cancelled: { text: localize("com_approval_status_cancelled"), cls: "bg-[#f7f8fa] text-[#86909c]" },
              };
              return (
                <div key={node.node_code ?? node.task_id ?? i} className="flex gap-3">
                  <div className="flex flex-col items-center">
                    <span className={cn("mt-1 h-3 w-3 shrink-0 rounded-full", dotColor)} />
                    {!isLast && <span className="mt-1 w-px flex-1 bg-[#e5e6eb]" />}
                  </div>
                  <div className={cn("min-w-0 flex-1", isLast ? "pb-1" : "pb-4")}>
                    {/* Node name + aggregate status badge */}
                    <div className="flex items-center gap-2">
                      <span className={cn("text-[14px] font-medium", isNotStarted ? "text-[#86909c]" : "text-[#1d2129]")}>
                        {node.node_name || "--"}
                      </span>
                      {!isNotStarted && nodeBadgeMap[s] && (
                        <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-medium", nodeBadgeMap[s].cls)}>
                          {nodeBadgeMap[s].text}
                        </span>
                      )}
                    </div>
                    {/* Per-approver entries */}
                    {matchedTasks.length > 0 && (
                      <div className="mt-2 space-y-1.5">
                        {matchedTasks.map((t) => {
                          const ts = String(t.status || "").toLowerCase();
                          const tLabel = ts === "approved" ? localize("com_approval_status_approved") :
                            ts === "rejected" ? localize("com_approval_status_rejected") :
                            ts === "pending" ? localize("com_approval_status_pending") :
                            ts === "skipped" ? localize("com_approval_status_skipped") :
                            ts === "cancelled" ? localize("com_approval_status_cancelled") :
                            localize("com_approval_node_not_started");
                          const tIconCls = ts === "approved" ? "text-[#00b42a]" : ts === "rejected" ? "text-[#f53f3f]" :
                            (ts === "skipped" || ts === "cancelled") ? "text-[#c9cdd4]" : "text-[#165dff]";
                          const tIcon = ts === "approved" ? "✓" : ts === "rejected" ? "✗" :
                            (ts === "skipped" || ts === "cancelled") ? "⊘" : "●";
                          return (
                            <div key={t.task_id ?? t.id} className="rounded-lg border border-[#f2f3f5] bg-[#fafbfc] px-3 py-2">
                              <div className="flex items-center justify-between gap-2">
                                <div className="flex items-center gap-1.5">
                                  <span className={cn("text-[12px] font-bold", tIconCls)}>{tIcon}</span>
                                  {t.approver_user_name && (
                                    <span className="text-[13px] text-[#1d2129]">{t.approver_user_name}</span>
                                  )}
                                  <span className="text-[12px] text-[#86909c]">{tLabel}</span>
                                </div>
                                {t.update_time && ts !== "pending" && (
                                  <span className="shrink-0 text-[11px] text-[#c9cdd4]">{formatTime(t.update_time)}</span>
                                )}
                              </div>
                              {t.comment && (
                                <div className="mt-1.5 rounded-lg bg-[#f0f1f3] px-3 py-1.5 text-[12px] text-[#4e5969] break-all">
                                  {t.comment}
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    )}
                    {/* Not-started placeholder */}
                    {isNotStarted && (
                      <div className="mt-0.5 text-[12px] text-[#86909c]">{localize("com_approval_node_not_started")}</div>
                    )}
                    {/* flow_nodes-only entry with no matched tasks */}
                    {!isNotStarted && matchedTasks.length === 0 && (
                      <div className="mt-0.5 text-[12px] text-[#86909c]">{
                        s === "approved" ? localize("com_approval_status_approved") :
                        s === "rejected" ? localize("com_approval_status_rejected") :
                        s === "pending" ? localize("com_approval_status_pending") :
                        s === "skipped" ? localize("com_approval_status_skipped") :
                        localize("com_approval_status_cancelled")
                      }</div>
                    )}
                  </div>
                </div>
              );
            });
          })()}
          {/* other action logs (withdrawn, cancelled, etc.) */}
          {(detail.action_logs || [])
            .filter((l) => l.action !== "submitted" && l.action !== "resubmitted")
            .map((log, i, arr) => (
              <TimelineStep key={log.id ?? `l${i}`} action={log.action} operatorName={log.operator_user_name}
                createTime={log.create_time} detail={log.detail} localize={localize} isLast={i === arr.length - 1} />
            ))}
        </div>
      )}
    </div>
  );
}
