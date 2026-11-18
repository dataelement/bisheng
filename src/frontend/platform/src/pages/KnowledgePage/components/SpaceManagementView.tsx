import { Breadcrumb, Button, Dropdown, DropdownItem, DropdownSeparator, Tooltip, type BreadcrumbItem } from "@bisheng/ui";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Outlined } from "bisheng-icons";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { PermissionDialog } from "@/components/bs-comp/permission/PermissionDialog";
import type { SpaceFolderParent } from "@/controllers/API/knowledgeFiles";
import { getMyResourcePermissionsApi } from "@/controllers/API/permission";
import { knowledgeSpaceApi, type KnowledgeSpaceInfo } from "@/controllers/API/knowledgeSpace";
import {
  knowledgeQueryKeys,
  type KnowledgeQueryScope,
} from "@/controllers/hooks/knowledge";
import { showApiError } from "@/controllers/request";
import { isErrorEnvelope } from "@bisheng/api-client";
import { useKnowledgeDeletion } from "../hooks/useKnowledgeDeletion";
import { KnowledgeDeletionDialog } from "./KnowledgeDeletionDialog";
import { SpaceMetadataPanel } from "./SpaceMetadataPanel";
import { SpaceTaskRecordsButton } from "./SpaceTaskRecordsButton";

interface SpaceFolderBreadcrumbProps {
  items: BreadcrumbItem[];
  spaceInfo: ReactNode;
}

function SpaceFolderBreadcrumb({ items, spaceInfo }: SpaceFolderBreadcrumbProps) {
  const { t } = useTranslation("knowledge");
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const element = ref.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  // Match the client cap and leave room for separators, space info and the
  // current name when the platform's resizable sidebar narrows the header.
  const parentCount = Math.min(items.length - 1, 3);
  const parentMaxWidth = width ? Math.min(128, Math.max(0, (width - 144) / parentCount)) : 128;

  return (
    <div ref={ref} className="min-w-0 flex-1">
      <Breadcrumb
        items={items}
        rootTrailing={spaceInfo}
        className="text-base leading-8"
        parentMaxWidth={parentMaxWidth}
        ariaLabel={t("f118.current_folder")}
        expandLabel={(count) => t("f118.expand_folders", { count })}
      />
    </div>
  );
}

interface SpaceManagementViewProps {
  scope: KnowledgeQueryScope;
  spaceId: number;
  title?: string;
  description?: string;
  spaceInfo?: Pick<KnowledgeSpaceInfo, "name" | "description">;
  parentId?: number | null;
  folderPath?: {
    parents: readonly SpaceFolderParent[];
    onOpenFolder: (id: number | null) => void;
  };
  onDeleted?: (id: number) => void;
  children?: (toolbarTarget: HTMLDivElement | null) => ReactNode;
}

export function SpaceManagementView({
  scope,
  spaceId,
  title = "",
  description,
  spaceInfo,
  parentId,
  folderPath,
  onDeleted,
  children,
}: SpaceManagementViewProps) {
  const { t } = useTranslation("knowledge");
  const location = useLocation();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const client = useQueryClient();
  const [toolbarTarget, setToolbarTarget] = useState<HTMLDivElement | null>(
    null,
  );
  const [permissionOpen, setPermissionOpen] = useState(false);
  const [metadataOpen, setMetadataOpen] = useState(false);
  const moreButton = useRef<HTMLButtonElement>(null);
  const deletionScope = JSON.stringify([scope, spaceId]);
  const currentDeletionScope = useRef<string | null>(deletionScope);
  currentDeletionScope.current = deletionScope;
  const deletion = useKnowledgeDeletion(deletionScope);
  useEffect(() => {
    currentDeletionScope.current = deletionScope;
    return () => {
      currentDeletionScope.current = null;
    };
  }, [deletionScope]);
  const permission = useQuery({
    queryKey: [...knowledgeQueryKeys.space(scope, spaceId), "detail-actions"],
    queryFn: () =>
      getMyResourcePermissionsApi("knowledge_space", String(spaceId), { showError: false }),
    enabled:
      Boolean(scope.identityKey) &&
      Number.isSafeInteger(spaceId) &&
      spaceId > 0,
    cacheTime: 0,
    retry: false,
    keepPreviousData: false,
  });
  useEffect(() => {
    if (permission.error && !(isErrorEnvelope(permission.error) && permission.error.status_code === 25022))
      showApiError(permission.error);
  }, [permission.error]);
  const canEdit = permission.data?.actions.includes("edit") === true;
  const canSeeSpace = permission.data?.actions.includes("visible") === true;
  const canManageMembers =
    permission.data?.actions.includes("manage_permission") === true;
  const canDelete = permission.data?.actions.includes("delete") === true;
  const overviewPath = scope.view === "admin" ? "/filelib?view=admin" : "/filelib";
  const canReadRoot = children ? parentId != null && (canEdit || canSeeSpace) : canEdit;
  const root = useQuery({
    queryKey: knowledgeQueryKeys.info(scope, spaceId),
    queryFn: () => knowledgeSpaceApi.getSpaceInfo(spaceId, { showError: false }),
    enabled: !spaceInfo && canReadRoot,
    cacheTime: 0,
    retry: false,
  });
  useEffect(() => {
    if (root.error && !(isErrorEnvelope(root.error) && root.error.status_code === 18000))
      showApiError(root.error);
  }, [root.error]);
  const rootInfo = spaceInfo ?? (canReadRoot && !root.isError ? root.data : undefined);
  const rootName = rootInfo?.name;
  const spaceTitle = rootName ?? title;
  const spaceDescription = rootInfo ? rootInfo.description : description;
  const tab = params.get("tab");
  const legacySettingsTab =
    tab === "settings" || tab === "defaults" || tab === "embedding" || tab === "jobs";
  const metadataVisible = canEdit && (metadataOpen || tab === "metadata");
  const settingsParams = new URLSearchParams(params);
  settingsParams.delete("tab");
  if (scope.view === "admin") settingsParams.set("view", "admin");
  else if (settingsParams.getAll("view").includes("admin")) settingsParams.delete("view");
  const settingsLocation = {
    pathname: `/filelib/${spaceId}/settings`,
    search: settingsParams.toString(),
    hash: location.hash,
  };
  const handleCloseMetadata = () => {
    setMetadataOpen(false);
    if (tab === "metadata") {
      if (!children) {
        navigate(overviewPath, { replace: true });
        return;
      }
      const next = new URLSearchParams(params);
      next.delete("tab");
      setParams(next, { replace: true });
    }
    requestAnimationFrame(() => moreButton.current?.focus({ preventScroll: true }));
  };
  const handleBack = () => {
    if (!folderPath) {
      navigate(overviewPath);
      return;
    }
    const { parents, onOpenFolder } = folderPath;
    if (parents.length) onOpenFolder(parents[parents.length - 2]?.id ?? null);
  };
  const handleDelete = async () => {
    if (!canDelete || deletion.view) return;
    const deleted = await deletion.open({ spaceId, kind: "delete" });
    if (currentDeletionScope.current !== deletionScope) return;
    if (!deleted) {
      requestAnimationFrame(() => moreButton.current?.focus({ preventScroll: true }));
      return;
    }
    if (onDeleted) onDeleted(spaceId);
    else if (currentDeletionScope.current === deletionScope) navigate(overviewPath, { replace: true });
    const viewKey = knowledgeQueryKeys.scope(scope);
    void client.invalidateQueries({
      queryKey: viewKey.slice(0, -1),
      predicate: ({ queryKey }) => {
        const [kind, id] = queryKey.slice(viewKey.length);
        return kind !== "space" || id !== spaceId;
      },
    }).catch(() => undefined);
  };
  if (canEdit && legacySettingsTab) return <Navigate to={settingsLocation} replace />;

  const spaceInfoButton = (children || spaceTitle) && (
    <Tooltip
      content={
        <span className="whitespace-pre-wrap [overflow-wrap:anywhere]">
          {`ID: ${spaceId}\n${t("f118.space_description")}: ${spaceDescription?.trim() || "-"}`}
        </span>
      }
    >
      <Button
        type="button"
        variant="text"
        color="default"
        size="small"
        iconOnly
        aria-label={t("detail.space_info")}
        className="shrink-0 text-text-3 hover:text-blue-500 [&_svg]:size-4"
      >
        <Outlined.Info aria-hidden="true" />
      </Button>
    </Tooltip>
  );

  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col">
      <header className="flex min-h-16 shrink-0 flex-wrap items-center justify-between gap-x-3 gap-y-2 px-4 py-2.5">
        <div className={`flex min-w-0 flex-1 items-center ${folderPath ? "-ml-2 basis-[min(100%,20rem)] gap-1" : "gap-2"}`}>
          {(parentId != null || !children) && (
            <Tooltip content={t("back")}>
              <Button
                variant="text"
                color="default"
                iconOnly
                aria-label={t("back")}
                disabled={folderPath?.parents.length === 0}
                onClick={handleBack}
              >
                <Outlined.ArrowLeft />
              </Button>
            </Tooltip>
          )}
          {folderPath && <span className="mx-1 h-4 w-px shrink-0 bg-border-base" aria-hidden />}
          {folderPath && folderPath.parents.length > 0 ? (
            <SpaceFolderBreadcrumb
              items={[
                {
                  key: "space",
                  title: rootName ?? t("f118.spaces"),
                  onClick: () => folderPath.onOpenFolder(null),
                },
                ...folderPath.parents.map((folder) => ({
                  key: String(folder.id),
                  title: String(folder.file_name),
                  onClick: () => folderPath.onOpenFolder(folder.id),
                })),
              ]}
              spaceInfo={spaceInfoButton}
            />
          ) : (
            <div className="flex min-w-0 items-center gap-1">
              <h1 className="min-w-0 truncate text-h4 text-text-1">{spaceTitle}</h1>
              {spaceInfoButton}
              {children && parentId === null && rootInfo && (
                <SpaceTaskRecordsButton
                  key={deletionScope}
                  scope={scope}
                  spaceId={spaceId}
                  canReadProcessing={canEdit}
                />
              )}
            </div>
          )}
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-3">
          {(canEdit || canManageMembers || canDelete) && (
            <Dropdown
              align="end"
              onCloseAutoFocus={(event) => {
                if (permissionOpen || metadataVisible || deletion.view) event.preventDefault();
              }}
              menu={
                <>
                  {canEdit && (
                    <>
                      <DropdownItem
                        icon={<Outlined.File aria-hidden />}
                        onSelect={() => setMetadataOpen(true)}
                      >
                        {t("detail.metadata")}
                      </DropdownItem>
                      <DropdownItem
                        icon={<Outlined.Edit aria-hidden />}
                        onSelect={() => navigate(settingsLocation)}
                      >
                        {t("detail.settings")}
                      </DropdownItem>
                    </>
                  )}
                  {canManageMembers && (
                    <DropdownItem
                      icon={<Outlined.PeopleSafe aria-hidden />}
                      onSelect={() => setPermissionOpen(true)}
                    >
                      {t("managePermission", { ns: "permission" })}
                    </DropdownItem>
                  )}
                  {canDelete && (
                    <>
                      {(canEdit || canManageMembers) && <DropdownSeparator />}
                      <DropdownItem
                        danger
                        icon={<Outlined.Delete aria-hidden />}
                        onSelect={() => { void handleDelete(); }}
                      >
                        {t("deletion.delete_space")}
                      </DropdownItem>
                    </>
                  )}
                </>
              }
            >
              <Button
                ref={moreButton}
                type="button"
                variant="outlined"
                color="default"
                iconOnly
                aria-label={t("more", { ns: "bs" })}
                className="shrink-0 [--radius:0.5rem]"
              >
                <Outlined.MoreCircle aria-hidden />
              </Button>
            </Dropdown>
          )}
          {children && <div ref={setToolbarTarget} />}
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
      {children ? (
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
          {children(toolbarTarget)}
        </div>
      ) : (
        !canEdit && !permission.isError && (
          <p role="status" className="px-4">
            {t(permission.isInitialLoading ? "f118.loading_space" : "noOperationPermission")}
          </p>
        )
      )}
      {metadataVisible && (
        <SpaceMetadataPanel
          scope={scope}
          spaceId={spaceId}
          onClose={handleCloseMetadata}
        />
      )}
      {permissionOpen && canManageMembers && (
        <PermissionDialog
          open
          onOpenChange={(open) => {
            setPermissionOpen(open);
            if (!open) requestAnimationFrame(() => moreButton.current?.focus({ preventScroll: true }));
          }}
          resourceType="knowledge_space"
          resourceId={String(spaceId)}
          resourceName={spaceTitle}
        />
      )}
      <KnowledgeDeletionDialog operation={deletion} />
    </div>
  );
}
