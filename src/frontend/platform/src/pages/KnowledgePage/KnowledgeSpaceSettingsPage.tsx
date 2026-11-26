import { Button } from "@bisheng/ui";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Navigate, useLocation, useNavigate, useParams } from "react-router-dom";
import { knowledgeQueryKeys } from "@/controllers/hooks/knowledge";
import { useKnowledgePageScope } from "@/hooks/useKnowledgePageScope";
import { LoadingState } from "@/components/bs-icons/loading/LoadingState";
import { KnowledgeScopeUnavailable } from "./components/KnowledgeScopeUnavailable";
import { SpacePanelFrame } from "./components/SpacePanelFrame";
import { SpaceSettingsEditor } from "./components/SpaceSettingsEditor";
import { parseKnowledgeId } from "./detail";

export function KnowledgeSpaceSettingsPage() {
  const { t } = useTranslation("knowledge");
  const { scopes, canManage, isLoading, retry } = useKnowledgePageScope();
  const client = useQueryClient();
  const location = useLocation();
  const navigate = useNavigate();
  const spaceId = parseKnowledgeId(useParams().id);
  if (spaceId === null) return <Navigate to="/filelib" replace />;

  const params = new URLSearchParams(location.search);
  const views = params.getAll("view");
  const admin = views.length === 1 && views[0] === "admin";
  params.delete("tab");
  if (admin && !canManage) params.delete("view");
  const search = params.toString();
  const directory = `/filelib/${spaceId}${search ? `?${search}` : ""}${location.hash}`;
  if (admin && !canManage) return <Navigate to={directory} replace />;

  const scope = admin ? scopes?.admin : scopes?.ordinary;
  const handleBack = () => navigate(directory, { replace: true });
  const handleSaved = () => {
    if (scope) return client.invalidateQueries({ queryKey: knowledgeQueryKeys.scope(scope) });
  };

  return (
    <main className="h-full min-h-0 min-w-0 bg-bg-page">
      {scope && !isLoading ? (
        <SpaceSettingsEditor scope={scope} spaceId={spaceId} onSaved={handleSaved} onBack={handleBack} />
      ) : (
        <SpacePanelFrame
          title={t("detail.settings")}
          presentation="page"
          contentClassName="h-full"
          back={{ label: t("back"), onClick: handleBack }}
          footer={
            <>
              <Button variant="outlined" color="default" onClick={handleBack}>{t("cancel")}</Button>
              {!isLoading && <Button onClick={() => { void retry(); }}>{t("retry")}</Button>}
            </>
          }
        >
          {isLoading ? <LoadingState size="page" className="h-full" label={t("f118.loading_space")} /> : <KnowledgeScopeUnavailable />}
        </SpacePanelFrame>
      )}
    </main>
  );
}
