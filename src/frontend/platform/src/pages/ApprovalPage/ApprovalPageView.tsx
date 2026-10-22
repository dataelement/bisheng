import { Tabs } from "@bisheng/ui";
import { ApprovalDialogs } from "./ApprovalDialogs";
import { ExceptionPanel } from "./ExceptionPanel";
import { FlowManagementPanel } from "./FlowManagementPanel";
import type { useApprovalController } from "./useApprovalController";
interface ApprovalPageViewProps {
  controller: ReturnType<typeof useApprovalController>;
}
export function ApprovalPageView({ controller }: ApprovalPageViewProps) {
  const { t, setActiveTab, loadPage, activeTab } = controller;
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
            void loadPage();
          }}
          items={[
            { key: "flow", label: t("approvalPage.tabFlow") },
            { key: "exception", label: t("approvalPage.tabException") },
          ]}
          className="mt-4"
          divider={false}
        />
      </div>

      <FlowManagementPanel controller={controller} />

      <ExceptionPanel controller={controller} />

      {/* ── Dialogs ─────────────────────────────────────────────────────────── */}
      <ApprovalDialogs controller={controller} />
    </div>
  );
}
