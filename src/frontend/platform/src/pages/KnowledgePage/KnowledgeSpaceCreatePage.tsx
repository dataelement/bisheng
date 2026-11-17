import { Button } from "@bisheng/ui";
import { useQueryClient } from "@tanstack/react-query";
import { useContext } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { userContext } from "@/contexts/userContext";
import { knowledgeQueryKeys } from "@/controllers/hooks/knowledge";
import { useKnowledgePageScope } from "@/hooks/useKnowledgePageScope";
import { CreateSpaceForm } from "./components/KnowledgeLibraryDialog";
import { SpacePanelFrame } from "./components/SpacePanelFrame";
import { canCreateKnowledgeSpace } from "./knowledgeSpaceCreation";

export function KnowledgeSpaceCreatePage() {
  const { t } = useTranslation("knowledge");
  const { user } = useContext(userContext);
  const { scopes, isLoading, retry } = useKnowledgePageScope();
  const client = useQueryClient();
  const location = useLocation();
  const navigate = useNavigate();
  if (!canCreateKnowledgeSpace(user)) return <Navigate to="/filelib" replace />;

  const from: unknown = location.state?.from;
  const returnPath =
    typeof from === "string" && /^\/filelib(?:\/[1-9]\d*)?\/?(?:[?#]|$)/.test(from)
      ? from
      : "/filelib";
  const handleCancel = () => navigate(returnPath, { replace: true });
  const scope = scopes?.ordinary;

  return (
    <main className="h-full min-h-0 min-w-0 bg-bg-page">
      {scope && !isLoading ? (
        <CreateSpaceForm
          key={JSON.stringify(knowledgeQueryKeys.scope(scope))}
          scope={scope}
          presentation="page"
          onCancel={handleCancel}
          onLoadEnd={async () => {
            const queryScope = knowledgeQueryKeys.scope(scope);
            await Promise.all([
              client.invalidateQueries({ queryKey: [...queryScope, "navigation-sections", "created"] }),
              client.invalidateQueries({ queryKey: [...queryScope, "navigation-catalog"] }),
            ]);
          }}
        />
      ) : (
        <SpacePanelFrame
          title={t("f118.create_space")}
          presentation="page"
          back={{ label: t("back"), onClick: handleCancel }}
          footer={
            <>
              <Button variant="outlined" color="default" onClick={handleCancel}>{t("cancel")}</Button>
              {!isLoading && <Button onClick={() => { void retry(); }}>{t("retry")}</Button>}
            </>
          }
        >
          <p role="status">{t(isLoading ? "f118.loading_space" : "f118.scope_unavailable")}</p>
        </SpacePanelFrame>
      )}
    </main>
  );
}
