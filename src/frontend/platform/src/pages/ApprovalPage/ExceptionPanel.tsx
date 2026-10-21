import { Button } from '@bisheng/ui';

import { Tag } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { formatDateTime, HIDDEN_DETAIL_KEYS } from "./approvalMetadata";
import { ActionBtn } from "./ApprovalPrimitives";
import { ApprovalTimeline } from "./ApprovalTimeline";

import type { useApprovalController } from "./useApprovalController";
interface ExceptionPanelProps {
  controller: ReturnType<typeof useApprovalController>;
}
export function ExceptionPanel({ controller }: ExceptionPanelProps) {
  const {
    activeTab,
    exceptions,
    t,
    handleRetryException,
    setExceptionPickerTempIds,
    setExceptionPickerTempNames,
    setExceptionPickerItem,
    setExceptionPickerOpen,
    setCancelDialogItem,
    setCancelReason,
    toggleExceptionProgress,
    expandedProgressIds,
    loadingProgressId,
    instanceDetailCache,
  } = controller;
  return (
    <>
      {" "}
      {activeTab === "exception" && (
        <div className="flex-1 overflow-y-auto p-6">
          {exceptions.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-64 text-sm text-muted-foreground">
              {t("approvalPage.noExceptions")}
            </div>
          ) : (
            <div className="space-y-3">
              {exceptions.map((item) => (
                <div key={item.id} className="rounded-xl border border-border bg-card p-4">
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <div className="flex items-center gap-2 flex-wrap">
                        <Tag
                          size="small"
                          color={item.exception_type === "execute_failed" ? "danger" : "warning"}
                          className="shrink-0 whitespace-nowrap"
                        >
                          {item.exception_type === "route_missing"
                            ? t("approvalPage.exceptionTypeMissing")
                            : item.exception_type === "approver_empty"
                              ? t("approvalPage.exceptionTypeEmpty")
                              : item.exception_type === "execute_failed"
                                ? t("approvalPage.exceptionTypeFailed")
                                : item.exception_type}
                        </Tag>
                        {/* open / resolved status badge */}
                        {item.status === "open" && (
                          <Tag size="small" color="warning" className="shrink-0 whitespace-nowrap">
                            {t("approvalPage.exceptionStatusOpen")}
                          </Tag>
                        )}
                        {item.status === "resolved" && (
                          <Tag size="small" color="success" className="shrink-0 whitespace-nowrap">
                            {t("approvalPage.exceptionStatusResolved")}
                          </Tag>
                        )}
                        <span className="text-xs text-muted-foreground">#{item.id}</span>
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        {t("approvalPage.exceptionInstanceInfo", {
                          id: item.instance_id ?? "--",
                          time: formatDateTime(item.create_time),
                        })}
                      </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      {/* route_missing / approver_empty: retry to re-match route or assign approver */}
                      {item.status === "open" && item.exception_type !== "execute_failed" && (
                        <ActionBtn variant="outline" onClick={() => void handleRetryException(item)}>
                          {t("approvalPage.retryAction")}
                        </ActionBtn>
                      )}
                      {/* execute_failed: retry handler */}
                      {item.status === "open" && item.exception_type === "execute_failed" && (
                        <>
                          <ActionBtn variant="outline" onClick={() => void handleRetryException(item)}>
                            {t("approvalPage.retryAction")}
                          </ActionBtn>
                          <ActionBtn
                            variant="outline"
                            onClick={() => void handleRetryException(item, { action: "mark_manually_completed" })}
                          >
                            {t("approvalPage.markManuallyCompletedAction")}
                          </ActionBtn>
                        </>
                      )}
                      {/* approver_empty: assign approvers / skip node */}
                      {item.status === "open" && item.exception_type === "approver_empty" && (
                        <>
                          <ActionBtn
                            variant="outline"
                            onClick={() => {
                              setExceptionPickerTempIds([]);
                              setExceptionPickerTempNames([]);
                              setExceptionPickerItem(item);
                              setExceptionPickerOpen(true);
                            }}
                          >
                            {t("approvalPage.assignApproversAction")}
                          </ActionBtn>
                          <ActionBtn
                            variant="outline"
                            onClick={() => void handleRetryException(item, { action: "skip_node" })}
                          >
                            {t("approvalPage.skipNodeAction")}
                          </ActionBtn>
                        </>
                      )}
                      {/* cancel: open exceptions only */}
                      {item.status === "open" && (
                        <ActionBtn
                          variant="outline"
                          className="border-red-300 text-red-600 hover:bg-red-50 dark:border-red-500/40 dark:text-red-400 dark:hover:bg-red-500/10"
                          onClick={() => {
                            setCancelDialogItem(item);
                            setCancelReason("");
                          }}
                        >
                          {t("approvalPage.cancelExceptionAction")}
                        </ActionBtn>
                      )}
                    </div>
                  </div>
                  {/* Business info row */}
                  {(item.business_name || item.scenario_name || item.applicant_user_name) && (
                    <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-xs text-muted-foreground">
                      {item.business_name && (
                        <span>
                          <span className="text-muted-foreground/70">{t("approvalPage.exceptionBusiness")}：</span>
                          <span className="font-medium text-foreground">{item.business_name}</span>
                        </span>
                      )}
                      {item.scenario_name && (
                        <span>
                          <span className="text-muted-foreground/70">{t("approvalPage.exceptionScenario")}：</span>
                          {item.scenario_name}
                        </span>
                      )}
                      {item.applicant_user_name && (
                        <span>
                          <span className="text-muted-foreground/70">{t("approvalPage.exceptionApplicant")}：</span>
                          {item.applicant_user_name}
                        </span>
                      )}
                    </div>
                  )}
                  {/* Detail key-value */}
                  {item.detail &&
                    Object.keys(item.detail).length > 0 &&
                    (() => {
                      const visibleEntries = Object.entries(item.detail).filter(
                        ([k, v]) => !HIDDEN_DETAIL_KEYS.has(k) && v !== null && v !== undefined && v !== "",
                      );
                      return visibleEntries.length > 0 ? (
                        <div className="mt-3 rounded-lg border border-border bg-gray-50 dark:bg-gray-50/[0.06] divide-y divide-border">
                          {visibleEntries.map(([k, v]) => (
                            <div key={k} className="flex items-start gap-3 px-3 py-2 text-xs">
                              <span className="w-36 shrink-0 text-muted-foreground/70">
                                {t(`approvalPage.exceptionDetailKey_${k}`, { defaultValue: k })}
                              </span>
                              <span className="break-all text-foreground">{String(v)}</span>
                            </div>
                          ))}
                        </div>
                      ) : null;
                    })()}
                  {/* error_summary for execute_failed */}
                  {item.exception_type === "execute_failed" && item.error_summary && (
                    <div className="mt-2 rounded-lg bg-red-50 border border-red-100 px-3 py-2 text-xs text-red-600 break-all dark:bg-red-500/10 dark:border-red-500/25 dark:text-red-400">
                      {item.error_summary}
                    </div>
                  )}
                  {/* approval progress toggle */}
                  {item.instance_id && (
                    <div className="mt-3">
                      <Button size="small" variant="text" type="button" onClick={() => void toggleExceptionProgress(item)} color="default">
                        {expandedProgressIds.has(item.id) ? (
                          <>
                            <Outlined.Up size={12} /> {t("subjectSearch.collapseProgress")}
                          </>
                        ) : (
                          <>
                            <Outlined.Down size={12} /> {t("subjectSearch.showProgress")}
                          </>
                        )}
                      </Button>
                      {expandedProgressIds.has(item.id) &&
                        (loadingProgressId === item.id ? (
                          <div className="mt-2 text-xs text-muted-foreground">{t("loading")}</div>
                        ) : instanceDetailCache[item.id] ? (
                          <ApprovalTimeline detail={instanceDetailCache[item.id]} />
                        ) : (
                          <div className="mt-2 text-xs text-muted-foreground">{t("subjectSearch.noProgress")}</div>
                        ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}{" "}
    </>
  );
}
