import { Button, Tabs } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";
import type { KnowledgeQueryScope } from "@/controllers/hooks/knowledge";
import { useKnowledgePageScope } from "@/hooks/useKnowledgePageScope";
import KnowledgeFile from "./KnowledgeFile";
import KnowledgeQa from "./KnowledgeQa";
import { KnowledgeSpaceWorkspace } from "./KnowledgeSpaceWorkspace";

const pageWindow = window as Window & { LibPage?: { type: string } };

export default function KnowledgePage() {
  const { t } = useTranslation("knowledge");
  const { id } = useParams();
  const navigate = useNavigate();
  const { scopes, isLoading, canManage, retry } = useKnowledgePageScope();
  const [toolbarTarget, setToolbarTarget] = useState<HTMLDivElement | null>(
    null,
  );
  const [active, setActive] = useState(
    () => pageWindow.LibPage?.type || "file",
  );
  const activeKey =
    id === undefined && (active === "qa" || (active === "admin" && canManage)) ? active : "file";
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
  const content = (scope: KnowledgeQueryScope | undefined, tree = false) =>
    scope ? (
      tree ? (
        <KnowledgeSpaceWorkspace key={JSON.stringify(scope)} scope={scope} routeId={id}>
          <KnowledgeFile scope={scope} toolbarTarget={toolbarTarget} />
        </KnowledgeSpaceWorkspace>
      ) : <KnowledgeFile key={JSON.stringify(scope)} scope={scope} toolbarTarget={toolbarTarget} />
    ) : (
      unavailable
    );
  return (
    <div className="relative h-full w-full px-2 pt-4">
      <Tabs
        activeKey={activeKey}
        onChange={(key) => {
          setActive(key);
          if (id !== undefined) navigate("/filelib");
        }}
        extra={<div ref={setToolbarTarget} />}
        className="mb-10 w-full [&>div:first-child]:mx-2 [&>div:first-child]:mb-2"
        items={[
          {
            key: "file",
            label: t("f118.spaces"),
            icon: <Outlined.Books aria-hidden="true" />,
            children: content(scopes?.ordinary, true),
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
