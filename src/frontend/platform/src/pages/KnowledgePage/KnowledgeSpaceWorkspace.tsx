import { Button } from "@bisheng/ui";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useContext, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { userContext } from "@/contexts/userContext";
import { LoadingState } from "@/components/bs-icons/loading/LoadingState";
import type { KnowledgeQueryScope } from "@/controllers/hooks/knowledge";
import { KnowledgeScopeUnavailable } from "./components/KnowledgeScopeUnavailable";
import { SpaceDetail, parseKnowledgeId } from "./detail";
import { canCreateKnowledgeSpace } from "./knowledgeSpaceCreation";
import { KnowledgeSpaceSidebar } from "./sidebar/KnowledgeSpaceSidebar";
import { rememberRetiredKnowledgeSpace, useInitialSpace } from "./sidebar/useInitialSpace";

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
  const client = useQueryClient();
  const { user } = useContext(userContext);
  const location = useLocation();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const spaceId = parseKnowledgeId(routeId);
  const parents = params.getAll("parent_id");
  const parentId = parents.length === 1 ? parseKnowledgeId(parents[0]) : null;
  const invalid =
    routeId !== undefined &&
    (spaceId === null ||
      (parents.length > 0 && (parents.length !== 1 || parentId === null)));
  const [retired, setRetired] = useState<ReadonlySet<number>>(() => new Set());
  const leaveDeletedSpace = useCallback((id: number) => {
    rememberRetiredKnowledgeSpace(client, scope, id);
    setRetired((current) => {
      if (current.has(id)) return current;
      const next = new Set(current);
      next.add(id);
      return next;
    });
    if (id === spaceId) {
      navigate(scope.view === "admin" ? "/filelib?view=admin" : "/filelib", { replace: true });
    }
  }, [client, navigate, scope, spaceId]);
  const initial = useInitialSpace(scope, active && routeId === undefined, retired);
  useEffect(() => {
    if (!active || routeId !== undefined || !initial.space || retired.has(initial.space.id)) return;
    const next = new URLSearchParams(params);
    next.delete("parent_id");
    next.delete("tab");
    next.delete("file_id");
    next.delete("process_file_id");
    if (scope.view === "admin") next.set("view", "admin");
    navigate(
      { pathname: `/filelib/${initial.space.id}`, search: next.toString() },
      { replace: true },
    );
  }, [initial.space, active, routeId, params, navigate, scope.view, retired]);
  const canCreate =
    scope.view === "ordinary" && canCreateKnowledgeSpace(user);
  const handleCreate = () => {
    navigate("/filelib/create", {
      state: { from: location.pathname + location.search + location.hash },
    });
  };
  const handleSelect = (
    id: number,
    folderId: number | null,
    showFiles = false,
  ) => {
    const next = new URLSearchParams(params);
    if (showFiles) next.delete("tab");
    next.delete("file_id");
    next.delete("process_file_id");
    if (scope.view === "admin") next.set("view", "admin");
    if (folderId === null) next.delete("parent_id");
    else next.set("parent_id", String(folderId));
    navigate({ pathname: `/filelib/${id}`, search: next.toString() });
  };
  if (!active) return null;
  return (
    <div className="flex h-full min-h-0 min-w-0 bg-bg-page">
      <KnowledgeSpaceSidebar
        scope={scope}
        spaceId={invalid ? undefined : (spaceId ?? undefined)}
        parentId={invalid ? null : parentId}
        canCopy={canCreate}
        onCreate={canCreate ? handleCreate : undefined}
        onSelect={(id, folderId) => handleSelect(id, folderId, true)}
        onDeleted={leaveDeletedSpace}
      />
      <main
        className="min-w-0 flex-1 overflow-auto"
        aria-label={t("workspace.files")}
      >
        {invalid ? (
          <KnowledgeScopeUnavailable />
        ) : spaceId !== null ? (
          <SpaceDetail
            key={JSON.stringify([scope, spaceId])}
            scope={scope}
            spaceId={spaceId}
            parentId={parentId}
            presentation="workspace"
            onOpenFolder={(id) => handleSelect(spaceId, id)}
            onDeleted={leaveDeletedSpace}
          />
        ) : !initial.error && (initial.loading || initial.space) ? (
          <LoadingState size="page" className="h-full" label={t("sidebar.loading")} />
        ) : (
          <div role="status" className="space-y-3 px-4 py-6">
            <p>
              {t(
                initial.error
                  ? "sidebar.load_failed"
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
