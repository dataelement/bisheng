import { Button, Tabs } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useKnowledgePageScope } from "@/hooks/useKnowledgePageScope";
import KnowledgeQa from "./KnowledgeQa";
import { KnowledgeSpaceAdminList } from "./KnowledgeSpaceAdminList";
import { KnowledgeSpaceWorkspace } from "./KnowledgeSpaceWorkspace";
import { SpaceManagementView } from "./components/SpaceManagementView";
import { parseKnowledgeId } from "./detail";

const pageWindow = window as Window & { LibPage?: { type: string } };

export default function KnowledgePage() {
  const { t } = useTranslation("knowledge");
  const { id } = useParams();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const { scopes, isLoading, canManage, retry } = useKnowledgePageScope();
  const [toolbarTarget, setToolbarTarget] = useState<HTMLDivElement | null>(
    null,
  );
  const [initialTab, setInitialTab] = useState(
    () => pageWindow.LibPage?.type || "file",
  );
  const views = params.getAll("view");
  const requested =
    views.length === 0
      ? id === undefined
        ? initialTab
        : "file"
      : views.length === 1
        ? views[0]
        : "file";
  const activeKey =
    requested === "admin" && canManage
      ? "admin"
      : requested === "qa" && id === undefined
        ? "qa"
        : "file";
  useEffect(() => {
    delete pageWindow.LibPage;
  }, []);
  const unavailable = (
    <div role="status" className="space-y-3 p-4">
      <p>{t(isLoading ? "f118.loading_space" : "f118.scope_unavailable")}</p>
      <Button
        disabled={isLoading}
        onClick={() => {
          void retry();
        }}
      >
        {t("retry")}
      </Button>
    </div>
  );
  const ordinary = scopes?.ordinary;
  const ordinaryContent = ordinary ? (
    <KnowledgeSpaceWorkspace
      key={JSON.stringify(ordinary)}
      scope={ordinary}
      routeId={id}
      active={activeKey === "file"}
    />
  ) : unavailable;
  const admin = scopes?.admin;
  const spaceId = parseKnowledgeId(id);
  const tab = params.get("tab");
  const isConfigurationLink = spaceId !== null && !params.has("file_id") && (
    tab === "settings" || tab === "metadata" || tab === "defaults" ||
    tab === "embedding" || tab === "jobs"
  );
  let adminContent = unavailable;
  if (activeKey === "admin" && admin) {
    if (isConfigurationLink) {
      adminContent = (
        <SpaceManagementView
          key={JSON.stringify([admin, spaceId])}
          scope={admin}
          spaceId={spaceId}
        />
      );
    } else if (id !== undefined) {
      adminContent = <Navigate to="/filelib?view=admin" replace />;
    } else {
      adminContent = (
        <KnowledgeSpaceAdminList key={JSON.stringify(admin)} scope={admin} toolbarTarget={toolbarTarget} />
      );
    }
  }
  return (
    <div className="relative h-full w-full px-2 pt-4">
      <Tabs
        activeKey={activeKey}
        onChange={(key) => {
          setInitialTab("file");
          navigate(key === "file" ? "/filelib" : `/filelib?view=${key}`);
        }}
        extra={<div ref={setToolbarTarget} />}
        className="flex h-full w-full flex-col [&>div:first-child]:mx-2 [&>div:first-child]:mb-2 [&>div:first-child]:shrink-0 [&>[role=tabpanel]]:min-h-0 [&>[role=tabpanel]]:flex-1"
        items={[
          {
            key: "file",
            label: t("f118.spaces"),
            icon: <Outlined.Books aria-hidden="true" />,
            children: ordinaryContent,
          },
          {
            key: "qa",
            label: t("lib.qaData", { ns: "bs" }),
            icon: <Outlined.BookOpenText aria-hidden="true" />,
            children: <KnowledgeQa toolbarTarget={toolbarTarget} />,
          },
          ...(canManage
            ? [
                {
                  key: "admin",
                  label: t("f118.manage_spaces"),
                  icon: <Outlined.Books aria-hidden="true" />,
                  children: adminContent,
                },
              ]
            : []),
        ]}
      />
    </div>
  );
}
