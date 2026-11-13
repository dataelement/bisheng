import { Button, Tabs } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import type { KnowledgeQueryScope } from "@/controllers/hooks/knowledge";
import { useKnowledgePageScope } from "@/hooks/useKnowledgePageScope";
import KnowledgeQa from "./KnowledgeQa";
import { KnowledgeSpaceWorkspace } from "./KnowledgeSpaceWorkspace";

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
  const content = (scope: KnowledgeQueryScope | undefined) =>
    scope ? (
      <KnowledgeSpaceWorkspace
        key={JSON.stringify(scope)}
        scope={scope}
        routeId={id}
        active={activeKey === (scope.view === "admin" ? "admin" : "file")}
      />
    ) : (
      unavailable
    );
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
            children: content(scopes?.ordinary),
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
                  children: content(scopes?.admin),
                },
              ]
            : []),
        ]}
      />
    </div>
  );
}
