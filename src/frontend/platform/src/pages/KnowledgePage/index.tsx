import { Button, Tabs } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useKnowledgePageScope } from "@/hooks/useKnowledgePageScope";
import { KnowledgeScopeUnavailable } from "./components/KnowledgeScopeUnavailable";
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
  const unavailable = isLoading ? (
    <p role="status" className="p-4">{t("f118.loading_space")}</p>
  ) : (
    <KnowledgeScopeUnavailable
      action={<Button onClick={() => { void retry(); }}>{t("retry")}</Button>}
    />
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
  const adminContent = canManage && admin ? (
    <KnowledgeSpaceWorkspace
      key={JSON.stringify(admin)}
      scope={admin}
      routeId={id}
      active={activeKey === "admin"}
    />
  ) : unavailable;
  return (
    <div className="relative h-full w-full px-2 pt-4">
      <Tabs
        activeKey={activeKey}
        onChange={(key) => {
          setInitialTab("file");
          navigate(key === "file" ? "/filelib" : `/filelib?view=${key}`);
        }}
        extra={<div ref={setToolbarTarget} />}
        className="flex h-full w-full flex-col [&>div:first-child]:mx-2 [&>div:first-child]:shrink-0 [&>[role=tabpanel]]:min-h-0 [&>[role=tabpanel]]:flex-1"
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
