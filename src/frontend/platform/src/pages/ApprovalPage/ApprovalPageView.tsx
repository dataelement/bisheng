import { Alert, Tabs } from "@bisheng/ui";
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
  const showLoadError = !!loadError && (!isApiError(loadError)
    || (loadError.kind !== 'canceled' && loadError.presentation !== 'global'));
  return (
    <div className="flex h-full flex-col bg-background-main-content">
      {/* page header */}
      <div className="border-b border-border px-6 pt-6 pb-0">
        <h1 className="text-xl font-semibold text-foreground">{t("approvalPage.title")}</h1>
        {/* tabs */}
        <Tabs
          activeKey={activeTab}
          onChange={(key) => {
            setActiveTab(key as "flow" | "exception");
            void loadPage().catch(showApiError);
          }}
          items={[
            { key: "flow", label: t("approvalPage.tabFlow") },
            { key: "exception", label: t("approvalPage.tabException") },
          ]}
          className="mt-4"
          divider={false}
        />
      </div>

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
