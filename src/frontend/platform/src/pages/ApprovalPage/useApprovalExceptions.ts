import { notification } from '@bisheng/ui';
import { showApiError } from '@/controllers/request';

import {
  cancelApprovalExceptionApi,
  getApprovalInstanceDetailForAdminApi,
  retryApprovalExceptionApi,
  type ApprovalExceptionItem,
  type ApprovalInstanceDetail,
} from "@/controllers/API/approval";
import { useState } from "react";
import { useTranslation } from "react-i18next";

interface ApprovalExceptionsOptions {
  loadPage: () => Promise<void>;
}
export function useApprovalExceptions({ loadPage }: ApprovalExceptionsOptions) {
  const { t } = useTranslation("bs");
  // ── exception actions ─────────────────────────────────────────────────────
  const handleRetryException = async (
    item: ApprovalExceptionItem,
    payload: { action?: string; approver_user_ids?: number[] } = {},
  ) => {
    try {
      await retryApprovalExceptionApi(item.id, payload);
      notification.open({ type: "success", title: String(t("approvalPage.hint") ?? ''), description: String(t("approvalPage.genericOperateSuccess") ?? '') });
      await loadPage();
    } catch (e) {
      showApiError(e);
    }
  };

  const [cancelDialogItem, setCancelDialogItem] = useState<ApprovalExceptionItem | null>(null);
  const [cancelReason, setCancelReason] = useState("");

  // exception approval progress state
  const [expandedProgressIds, setExpandedProgressIds] = useState<Set<number>>(new Set());
  const [instanceDetailCache, setInstanceDetailCache] = useState<Record<number, ApprovalInstanceDetail>>({});
  const [loadingProgressId, setLoadingProgressId] = useState<number | null>(null);

  const toggleExceptionProgress = async (item: ApprovalExceptionItem) => {
    const id = item.id;
    if (expandedProgressIds.has(id)) {
      setExpandedProgressIds((prev) => {
        const s = new Set(prev);
        s.delete(id);
        return s;
      });
      return;
    }
    setExpandedProgressIds((prev) => {
      const s = new Set(prev);
      s.add(id);
      return s;
    });
    if (!item.instance_id || instanceDetailCache[id]) return;
    setLoadingProgressId(id);
    try {
      const detail = await getApprovalInstanceDetailForAdminApi(item.instance_id);
      setInstanceDetailCache((prev) => ({ ...prev, [id]: detail }));
    } catch (error) {
      showApiError(error);
      setExpandedProgressIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    } finally {
      setLoadingProgressId(null);
    }
  };

  const handleCancelException = async () => {
    if (!cancelDialogItem) return;
    if (!cancelReason.trim()) {
      notification.open({ type: "error", title: String(t("approvalPage.hint") ?? ''), description: String(t("approvalPage.cancelReasonRequired") ?? '') });
      return;
    }
    try {
      await cancelApprovalExceptionApi(cancelDialogItem.id, cancelReason.trim());
      notification.open({ type: "success", title: String(t("approvalPage.hint") ?? ''), description: String(t("approvalPage.genericOperateSuccess") ?? '') });
      setCancelDialogItem(null);
      setCancelReason("");
      await loadPage();
    } catch (e) {
      showApiError(e);
    }
  };

  return {
    handleRetryException,
    cancelDialogItem,
    setCancelDialogItem,
    cancelReason,
    setCancelReason,
    handleCancelException,
    toggleExceptionProgress,
    expandedProgressIds,
    loadingProgressId,
    instanceDetailCache,
  };
}
