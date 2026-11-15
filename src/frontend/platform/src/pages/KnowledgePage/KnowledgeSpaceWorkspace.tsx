import { Button } from "@bisheng/ui";
import { useContext, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router-dom";
import { userContext } from "@/contexts/userContext";
import { type KnowledgeQueryScope } from "@/controllers/hooks/knowledge";
import { SpaceDetail, parseKnowledgeId } from "./detail";
import { KnowledgeSpaceSidebar } from "./sidebar/KnowledgeSpaceSidebar";
import { useInitialSpace } from "./sidebar/useInitialSpace";

interface KnowledgeSpaceWorkspaceProps {
  scope: KnowledgeQueryScope;
  routeId?: string;
  active?: boolean;
}

/** Restore the pre-homepage client layout without importing client state or APIs. */
export function KnowledgeSpaceWorkspace({
  scope,
  routeId,
  active = true,
}: KnowledgeSpaceWorkspaceProps) {
  const { t } = useTranslation("knowledge");
  const { user } = useContext(userContext);
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const spaceId = parseKnowledgeId(routeId);
  const parents = params.getAll("parent_id");
  const parentId = parents.length === 1 ? parseKnowledgeId(parents[0]) : null;
  const invalid =
    routeId !== undefined &&
    (spaceId === null ||
      (parents.length > 0 && (parents.length !== 1 || parentId === null)));
  const initial = useInitialSpace(scope, active && routeId === undefined);
  useEffect(() => {
    if (!active || routeId !== undefined || !initial.space) return;
    const next = new URLSearchParams(params);
    next.delete("parent_id");
    next.delete("tab");
    next.delete("file_id");
    navigate(
      { pathname: `/filelib/${initial.space.id}`, search: next.toString() },
      { replace: true },
    );
  }, [initial.space, active, routeId, params, navigate]);
  const canCreate =
    user?.is_global_super === true ||
    user?.is_child_admin === true ||
    user?.web_menu?.includes("create_knowledge") === true;
  const handleSelect = (
    id: number,
    folderId: number | null,
    showFiles = false,
  ) => {
    const next = new URLSearchParams(params);
    if (showFiles) next.delete("tab");
    next.delete("file_id");
    if (folderId === null) next.delete("parent_id");
    else next.set("parent_id", String(folderId));
    navigate({ pathname: `/filelib/${id}`, search: next.toString() });
  };
  if (!active) return null;
  return (
    <div className="flex h-full min-h-0 min-w-0">
      <KnowledgeSpaceSidebar
        scope={scope}
        spaceId={invalid ? undefined : (spaceId ?? undefined)}
        parentId={invalid ? null : parentId}
        canCopy={scope.view === "ordinary" && canCreate}
        onSelect={(id, folderId) => handleSelect(id, folderId, true)}
        onDeleted={(id) => {
          if (id === spaceId)
            navigate(
              scope.view === "admin" ? "/filelib?view=admin" : "/filelib",
              { replace: true },
            );
        }}
      />
      <main
        className="min-w-0 flex-1 overflow-auto px-4"
        aria-label={t("workspace.files")}
      >
        {invalid ? (
          <p role="status">{t("f118.scope_unavailable")}</p>
        ) : spaceId !== null ? (
          <SpaceDetail
            key={JSON.stringify([scope, spaceId, parentId])}
            scope={scope}
            spaceId={spaceId}
            parentId={parentId}
            presentation="workspace"
            onOpenFolder={(id) => handleSelect(spaceId, id)}
          />
        ) : (
          <div role="status" className="space-y-3 py-6">
            <p>
              {t(
                initial.error
                  ? "sidebar.load_failed"
                  : initial.loading || initial.space
                    ? "sidebar.loading"
                    : "sidebar.empty",
              )}
            </p>
            {initial.error && (
              <Button
                variant="text"
                onClick={() => {
                  void initial.retry();
                }}
              >
                {t("retry")}
              </Button>
            )}
          </div>
        )}
      </main>
    </div>
  );
}
