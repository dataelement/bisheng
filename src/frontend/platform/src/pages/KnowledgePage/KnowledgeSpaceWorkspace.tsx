import { useQueryClient } from "@tanstack/react-query";
import { useContext, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router-dom";
import { userContext } from "@/contexts/userContext";
import { knowledgeQueryKeys, type KnowledgeQueryScope } from "@/controllers/hooks/knowledge";
import { getWorkspaceClientUrl } from "@/utils/workspaceUrl";
import { KnowledgeLibraryDialog } from "./components/KnowledgeLibraryDialog";
import { SpaceDetail, parseKnowledgeId } from "./detail";
import { KnowledgeSpaceSidebar } from "./sidebar/KnowledgeSpaceSidebar";

interface KnowledgeSpaceWorkspaceProps {
  scope: KnowledgeQueryScope;
  routeId?: string;
  children: ReactNode;
}

/** Restore the pre-homepage client layout without importing client state or APIs. */
export function KnowledgeSpaceWorkspace({ scope, routeId, children }: KnowledgeSpaceWorkspaceProps) {
  const { t } = useTranslation("knowledge");
  const { user } = useContext(userContext);
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const client = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const spaceId = parseKnowledgeId(routeId);
  const parents = params.getAll("parent_id");
  const parentId = parents.length === 1 ? parseKnowledgeId(parents[0]) : null;
  const invalid = routeId !== undefined && (
    spaceId === null || (parents.length > 0 && (parents.length !== 1 || parentId === null))
  );
  const canCreate = user?.is_global_super === true || user?.is_child_admin === true ||
    user?.web_menu?.includes("create_knowledge") === true;
  const handleSelect = (id: number, folderId: number | null) => {
    const next = new URLSearchParams(params);
    if (folderId === null) next.delete("parent_id");
    else next.set("parent_id", String(folderId));
    navigate({ pathname: `/filelib/${id}`, search: next.toString() });
  };
  return (
    <div className="flex h-[calc(100vh-120px-var(--license-banner-h,0px))] min-h-0 min-w-0">
      <KnowledgeSpaceSidebar
        scope={scope}
        spaceId={invalid ? undefined : spaceId ?? undefined}
        parentId={invalid ? null : parentId}
        canCreate={canCreate}
        onCreate={() => setCreateOpen(true)}
        onSelect={handleSelect}
        onOverview={() => navigate("/filelib")}
        onSquare={() => window.open(getWorkspaceClientUrl("/knowledge?square=1"), "_blank", "noopener,noreferrer")}
      />
      <main className="min-w-0 flex-1 overflow-auto px-4" aria-label={t("workspace.files")}>
        {invalid ? <p role="status">{t("f118.scope_unavailable")}</p> : spaceId !== null ? (
          <SpaceDetail
            key={JSON.stringify([scope, spaceId, parentId])}
            scope={scope}
            spaceId={spaceId}
            parentId={parentId}
            presentation="workspace"
            onOpenFolder={(id) => handleSelect(spaceId, id)}
          />
        ) : children}
      </main>
      {canCreate && <KnowledgeLibraryDialog
        scope={scope}
        datalist={[]}
        open={createOpen}
        onOpenChange={setCreateOpen}
        onLoadEnd={async () => {
          await client.invalidateQueries({ queryKey: knowledgeQueryKeys.scope(scope) });
        }}
      />}
    </div>
  );
}
