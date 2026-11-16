import { Button, Tabs, Tooltip } from "@bisheng/ui";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Outlined } from "bisheng-icons";
import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router-dom";
import { PermissionDialog } from "@/components/bs-comp/permission/PermissionDialog";
import { getMyResourcePermissionsApi } from "@/controllers/API/permission";
import { knowledgeSpaceApi } from "@/controllers/API/knowledgeSpace";
import {
  knowledgeQueryKeys,
  type KnowledgeQueryScope,
} from "@/controllers/hooks/knowledge";
import { showApiError } from "@/controllers/request";
import { KnowledgeSpaceSettingsPanel } from "./KnowledgeLibraryDialog";
import { ProcessingDefaultsPanel } from "./ProcessingDefaultsDialog";
import { SpaceMetadataPanel } from "./SpaceMetadataPanel";
import { SpaceModelIndexPanel } from "./SpaceModelIndexPanel";

interface SpaceManagementViewProps {
  scope: KnowledgeQueryScope;
  spaceId: number;
  title: string;
  description?: string;
  parentId?: number | null;
  children: (toolbarTarget: HTMLDivElement | null) => ReactNode;
}

export function SpaceManagementView({
  scope,
  spaceId,
  title,
  description,
  parentId,
  children,
}: SpaceManagementViewProps) {
  const { t } = useTranslation("knowledge");
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const client = useQueryClient();
  const [toolbarTarget, setToolbarTarget] = useState<HTMLDivElement | null>(
    null,
  );
  const [permissionOpen, setPermissionOpen] = useState(false);
  const permission = useQuery({
    queryKey: [...knowledgeQueryKeys.space(scope, spaceId), "detail-actions"],
    queryFn: () =>
      getMyResourcePermissionsApi("knowledge_space", String(spaceId)),
    enabled:
      Boolean(scope.identityKey) &&
      Number.isSafeInteger(spaceId) &&
      spaceId > 0,
    cacheTime: 0,
    retry: false,
    keepPreviousData: false,
  });
  useEffect(() => {
    if (permission.error) showApiError(permission.error);
  }, [permission.error]);
  const canEdit = permission.data?.actions.includes("edit") === true;
  const canManageMembers =
    permission.data?.actions.includes("manage_permission") === true;
  const root = useQuery({
    queryKey: knowledgeQueryKeys.info(scope, spaceId),
    queryFn: () => knowledgeSpaceApi.getSpaceInfo(spaceId),
    enabled: canEdit && parentId != null,
    cacheTime: 0,
    retry: false,
  });
  useEffect(() => {
    if (root.error) showApiError(root.error);
  }, [root.error]);
  const spaceTitle = root.data?.name ?? title;
  const spaceDescription = root.data?.description ?? description;
  const handleSaved = async () => {
    await client.invalidateQueries({
      queryKey: knowledgeQueryKeys.scope(scope),
    });
  };
  const items = [
    {
      key: "files",
      label: t("detail.files"),
      children: children(toolbarTarget),
    },
    ...(canEdit
      ? [
          {
            key: "defaults",
            label: t("detail.defaults"),
            children: (
              <ProcessingDefaultsPanel scope={scope} spaceId={spaceId} />
            ),
          },
          {
            key: "metadata",
            label: t("detail.metadata"),
            children: (
              <SpaceMetadataPanel
                scope={scope}
                spaceId={spaceId}
                onSaved={() => {
                  void handleSaved();
                }}
              />
            ),
          },
          {
            key: "embedding",
            label: t("detail.embedding"),
            children: (
              <SpaceModelIndexPanel scope={scope} spaceId={spaceId} onSaved={() => { void handleSaved(); }} />
            ),
          },
          {
            key: "settings",
            label: t("detail.settings"),
            children: (
              <KnowledgeSpaceSettingsPanel
                scope={scope}
                spaceId={spaceId}
                onSaved={handleSaved}
              />
            ),
          },
        ]
      : []),
  ];
  const requested = params.get("tab") === "jobs" ? "embedding" : params.get("tab") ?? "files";
  useEffect(() => {
    if (params.get("tab") !== "jobs") return;
    const next = new URLSearchParams(params);
    next.set("tab", "embedding");
    setParams(next, { replace: true });
  }, [params, setParams]);
  const active = items.some((item) => item.key === requested)
    ? requested
    : "files";
  const showBackButton = parentId != null;
  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col">
      <header className="flex min-h-16 shrink-0 flex-wrap items-center justify-between gap-x-3 gap-y-2 px-4 py-2.5">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          {showBackButton && (
            <Tooltip content={t("back")}>
              <Button
                variant="text"
                color="default"
                iconOnly
                aria-label={t("back")}
                onClick={() => navigate(scope.view === "admin" ? "/filelib?view=admin" : "/filelib")}
              >
                <Outlined.ArrowLeft />
              </Button>
            </Tooltip>
          )}
          <div className="min-w-0">
            <h1 className="truncate text-h4 text-text-1">
              {spaceTitle}
            </h1>
            <p className="truncate text-caption text-text-3" title={spaceDescription}>
              ID: {spaceId}
              {spaceDescription ? ` · ${spaceDescription}` : ""}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {canManageMembers && (
            <Button
              variant="outlined"
              color="default"
              onClick={() => setPermissionOpen(true)}
            >
              {t("detail.members")}
            </Button>
          )}
          <div ref={setToolbarTarget} />
        </div>
      </header>
      {permission.isError && (
        <Button
          variant="text"
          className="mx-4 self-start"
          onClick={() => {
            void permission.refetch();
          }}
        >
          {t("retry")}
        </Button>
      )}
      {items.length > 1 ? (
        <Tabs
          variant="neutral"
          activeKey={active}
          items={items}
          className={`flex min-h-0 flex-1 flex-col [&>div:first-child]:shrink-0 [&>div:first-child]:px-4 [&>[role=tabpanel]]:min-h-0 [&>[role=tabpanel]]:flex-1 [&>[role=tabpanel][data-state=active]]:flex [&>[role=tabpanel]]:flex-col ${active === "files" ? "[&>[role=tabpanel]]:overflow-hidden" : "[&>[role=tabpanel]]:overflow-auto [&>[role=tabpanel]]:px-4"}`}
          onChange={(key) => {
            const next = new URLSearchParams(params);
            if (key === "files") next.delete("tab");
            else next.set("tab", key);
            setParams(next);
          }}
        />
      ) : (
        children(toolbarTarget)
      )}
      {permissionOpen && canManageMembers && (
        <PermissionDialog
          open
          onOpenChange={setPermissionOpen}
          resourceType="knowledge_space"
          resourceId={String(spaceId)}
          resourceName={spaceTitle}
        />
      )}
    </div>
  );
}
