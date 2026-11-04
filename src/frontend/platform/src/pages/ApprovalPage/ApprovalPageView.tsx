import { Alert, Segmented } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { showApiError } from '@/controllers/request';
import { isApiError } from '@bisheng/api-client';
import { ApprovalDialogs } from "./ApprovalDialogs";
import { ExceptionPanel } from "./ExceptionPanel";
import { FlowManagementPanel } from "./FlowManagementPanel";
import type { useApprovalController } from "./useApprovalController";
interface ApprovalPageViewProps {
  controller: ReturnType<typeof useApprovalController>;
}
export function ApprovalPageView({ controller }: ApprovalPageViewProps) {
  const { t, setActiveTab, loadPage, loadError, activeTab } = controller;
  const [headerTarget, setHeaderTarget] = useState<HTMLElement | null>(null);
  useEffect(() => {
    setHeaderTarget(document.getElementById("approval-header-menu"));
  }, []);
  const showLoadError = !!loadError && (!isApiError(loadError)
    || (loadError.kind !== 'canceled' && loadError.presentation !== 'global'));
  return (
    <div className="flex h-full flex-col bg-background-main-content">
      {headerTarget && createPortal(
        <Segmented
          size="large"
          className="rounded-full [&>span[aria-hidden]]:rounded-full"
          aria-label={t("approvalPage.title")}
          value={activeTab}
          onChange={(value) => {
            setActiveTab(value as "flow" | "exception");
            void loadPage().catch(showApiError);
          }}
          options={[
            { value: "flow", label: t("approvalPage.tabFlow"), icon: <Outlined.ListTree aria-hidden="true" /> },
            { value: "exception", label: t("approvalPage.tabException"), icon: <Outlined.Attention aria-hidden="true" /> },
          ]}
        />,
        headerTarget,
      )}

      {showLoadError && <Alert type="error" live
        description={loadError instanceof Error ? loadError.message : t('api_errors:fallback')}
        actions={[{ label: t('subjectSearch.retry'), onClick: () => void loadPage().catch(showApiError) }]} />}

      <FlowManagementPanel controller={controller} />

      <ExceptionPanel controller={controller} />

      {/* ── Dialogs ─────────────────────────────────────────────────────────── */}
      <ApprovalDialogs controller={controller} />
    </div>
  );
}
