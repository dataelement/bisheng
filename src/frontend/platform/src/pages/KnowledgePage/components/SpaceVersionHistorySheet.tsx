import { LoadingState } from "@/components/bs-icons/loading/LoadingState";
import { Button, Tooltip } from "@bisheng/ui";
import {
  VersionHistoryAction,
  VersionHistoryStatusBadge,
  VersionHistorySummary,
  VersionHistoryTable,
  versionDialogStyles as styles,
  type SimilarDocumentFile,
} from "@bisheng/knowledge";
import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle, Trash2 } from "lucide-react";
import { Outlined } from "bisheng-icons";
import { useContext, useEffect, useId, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/bs-ui/sheet";
import { cname } from "@/components/bs-ui/utils";
import {
  knowledgeVersionsApi,
  type KnowledgeVersionsApi,
} from "@/controllers/API/knowledgeVersions";
import {
  knowledgeQueryKeys,
  type KnowledgeQueryScope,
} from "@/controllers/hooks/knowledge";
import { showApiError } from "@/controllers/request";
import { getMyResourcePermissionsApi } from "@/controllers/API/permission";
import { locationContext } from "@/contexts/locationContext";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { KnowledgeScopeUnavailable } from "./KnowledgeScopeUnavailable";
import { SpaceVersionRelationPanel } from "./SpaceVersionRelationPanel";
import { SpaceVersionUploadPanel } from "./SpaceVersionUploadPanel";
import { SpaceSimilarDocumentDialog } from "./SpaceSimilarDocumentDialog";
import { SpaceFileTools } from "./SpaceFileTools";
import { FILE_STATUSES, StatusIndicator } from "./KnowledgeFileStatus";

interface SpaceVersionHistorySheetProps {
  scope: KnowledgeQueryScope;
  spaceId: number;
  parentId: number | null;
  fileId: number | null;
  file?: SimilarDocumentFile;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  hasSimilar?: boolean;
  initialPanel?: "merge" | "similar" | null;
  api?: Partial<KnowledgeVersionsApi>;
}

export function SpaceVersionHistorySheet(props: SpaceVersionHistorySheetProps) {
  const { appConfig } = useContext(locationContext);
  const targetKey = JSON.stringify([
    ...knowledgeQueryKeys.space(props.scope, props.spaceId),
    props.parentId,
    props.fileId,
    appConfig.versionManagementEnabled === true,
  ]);
  const epoch = useMemo(() => ({ targetKey }), [targetKey]);
  const [similarTarget, setSimilarTarget] = useState<typeof epoch | null>(null);
  const handleOpenChange = (open: boolean) => {
    if (!open) setSimilarTarget(null);
    props.onOpenChange(open);
  };
  if (props.open && appConfig.versionManagementEnabled === true && props.fileId !== null &&
      (props.initialPanel === "similar" || similarTarget === epoch)) {
    return <SpaceSimilarDocumentDialog scope={props.scope} spaceId={props.spaceId} restrictToFileIds={[props.fileId]}
      api={{ ...knowledgeVersionsApi, ...props.api }} onOpenChange={handleOpenChange} />;
  }
  return (
    <Sheet open={props.open} onOpenChange={handleOpenChange}>
      {props.open && <HistoryContent key={targetKey} {...props} onSimilar={() => setSimilarTarget(epoch)} />}
    </Sheet>
  );
}

function HistoryContent({
  scope,
  spaceId,
  parentId,
  fileId,
  hasSimilar = false,
  initialPanel = null,
  api: customApi,
  onSimilar,
}: SpaceVersionHistorySheetProps & { onSimilar: () => void }) {
  const { t } = useTranslation("knowledge");
  const isManagement = initialPanel === "merge";
  const closeLabel = t("close", { ns: "bs" });
  const { appConfig } = useContext(locationContext);
  const api = { ...knowledgeVersionsApi, ...customApi };
  const client = useQueryClient();
  const [panel, setPanel] = useState<"upload" | "merge" | null>(
    initialPanel === "merge" ? "merge" : null,
  );
  const [busy, setBusy] = useState(false),
    [uncertain, setUncertain] = useState(false);
  const writing = useRef(false),
    lifetime = useRef<AbortController>();
  useEffect(() => {
    const controller = new AbortController();
    lifetime.current = controller;
    return () => {
      controller.abort();
    };
  }, []);
  // An unmounted opening never shares a later opening's request or cache.
  const openingId = useId();
  const validId = (id: number) => Number.isSafeInteger(id) && id > 0;
  const enabled =
    Boolean(scope.identityKey) &&
    validId(scope.tenantId) &&
    validId(spaceId) &&
    fileId !== null &&
    validId(fileId) &&
    (parentId === null || validId(parentId));
  const query = useQuery({
    queryKey: [
      ...knowledgeQueryKeys.space(scope, spaceId),
      "version-history",
      parentId,
      fileId,
      openingId,
    ],
    enabled,
    queryFn: ({ signal }) => api.getSpaceFileVersions(fileId!, signal),
    retry: false,
    cacheTime: 0,
    keepPreviousData: false,
  });
  useEffect(() => {
    if (query.isError) showApiError(query.error);
  }, [query.isError, query.error]);
  const data =
    query.isError || query.data?.knowledge_id !== spaceId
      ? undefined
      : query.data;
  const permissions = useQuery({
    queryKey: [...knowledgeQueryKeys.space(scope, spaceId), "version-actions", openingId],
    queryFn: () => getMyResourcePermissionsApi("knowledge_space", String(spaceId)),
    enabled: enabled && appConfig.versionManagementEnabled === true,
    retry: false,
    cacheTime: 0,
  });
  const containerPermissions = useQuery({
    queryKey: [...knowledgeQueryKeys.space(scope, spaceId), "version-upload-actions", parentId, openingId],
    queryFn: () => getMyResourcePermissionsApi(parentId === null ? "knowledge_space" : "folder", String(parentId ?? spaceId)),
    enabled: enabled && appConfig.versionManagementEnabled === true,
    retry: false,
    cacheTime: 0,
  });
  const permissionError = permissions.error || containerPermissions.error;
  useEffect(() => {
    if (permissionError) showApiError(permissionError);
  }, [permissionError]);
  const operationsEnabled =
    appConfig.versionManagementEnabled === true && enabled && !!data &&
    permissions.isSuccess && !permissions.isFetching && permissions.data?.actions?.includes("edit") === true;
  const canUploadVersion = operationsEnabled && containerPermissions.isSuccess &&
    !containerPermissions.isFetching && containerPermissions.data?.actions?.includes("upload_file") === true;
  const historicalVersions = data?.versions.filter(version => !version.is_primary) ?? [];
  const deletePermissions = useQueries({
    queries: historicalVersions.map(version => ({
      queryKey: [...knowledgeQueryKeys.space(scope, spaceId), "version-delete-actions", version.knowledge_file_id, openingId],
      queryFn: () => getMyResourcePermissionsApi("knowledge_file", String(version.knowledge_file_id)),
      enabled: operationsEnabled,
      retry: false,
      cacheTime: 0,
    })),
  });
  const deleteError = deletePermissions.find(permission => permission.isError)?.error;
  useEffect(() => {
    if (deleteError) showApiError(deleteError);
  }, [deleteError]);
  const canDeleteVersion = (versionId: number) => {
    const permission = deletePermissions[historicalVersions.findIndex(version => version.version_id === versionId)];
    return operationsEnabled && permission?.isSuccess && !permission.isFetching && permission.data?.actions?.includes("delete") === true;
  };
  const handleChanged = async () => {
    if (lifetime.current?.signal.aborted) return;
    setPanel(null);
    await client.invalidateQueries({
      queryKey: knowledgeQueryKeys.space(scope, spaceId),
    });
  };
  const handleMutation = (
    versionId: number,
    operation: "primary" | "delete",
  ) => {
    const controller = lifetime.current;
    if (
      !operationsEnabled ||
      (operation === "delete" && !canDeleteVersion(versionId)) ||
      !controller ||
      controller.signal.aborted ||
      writing.current ||
      uncertain
    )
      return;
    let attempted = false;
    bsConfirm({
      title: t(
        operation === "primary"
          ? "versions.set_primary"
          : "versions.delete_history",
      ),
      desc: t(
        operation === "primary"
          ? "versions.confirm_primary"
          : "versions.confirm_delete",
      ),
      signal: controller.signal,
      onOk: async (close) => {
        if (controller.signal.aborted || writing.current || attempted) return;
        attempted = true;
        writing.current = true;
        setBusy(true);
        try {
          if (operation === "primary")
            await api.setSpacePrimaryVersion(versionId, controller.signal);
          else await api.deleteSpaceFileVersion(versionId, controller.signal);
          if (controller.signal.aborted) return;
          close();
          await handleChanged();
        } catch (error) {
          if (!controller.signal.aborted) {
            setUncertain(true);
            close();
            showApiError(error);
          }
        } finally {
          writing.current = false;
          if (!controller.signal.aborted) setBusy(false);
        }
      },
    });
  };
  return (
    <SheetContent
      side="bottom"
      noClose
      aria-describedby={undefined}
      overlayClassName="z-modal bg-black/40 dark:bg-black/60"
      className={cname(
        "z-modal flex h-[60dvh] max-h-[90dvh] flex-col gap-0 overflow-hidden rounded-t-2xl border-border-base bg-bg-page text-text-1 shadow-modal outline-none dark:bg-bg-page",
        "data-[state=closed]:duration-200 data-[state=open]:[animation-duration:240ms] motion-reduce:animate-none",
        "min-[576px]:inset-y-0 min-[576px]:left-auto min-[576px]:h-full min-[576px]:max-h-none min-[576px]:w-[min(400px,calc(100vw-96px))] min-[576px]:rounded-none min-[576px]:border-l min-[576px]:border-t-0",
        "min-[576px]:data-[state=closed]:slide-out-to-right min-[576px]:data-[state=closed]:[--tw-exit-translate-y:0] min-[576px]:data-[state=open]:slide-in-from-right min-[576px]:data-[state=open]:[--tw-enter-translate-y:0]",
      )}
    >
      <div aria-hidden className="mx-auto mt-2 h-1 w-8 shrink-0 rounded-full bg-fill-3 min-[576px]:hidden" />
      <SheetHeader className="h-14 shrink-0 flex-row items-center justify-between gap-3 space-y-0 border-b border-border-base px-5 text-left">
        <SheetTitle title={isManagement ? data?.title : undefined} className="m-0 min-w-0 truncate text-base font-medium text-text-1">
          {isManagement
            ? data?.title ?? t("f118.version_history")
            : t("knowledge.version.history.title", { ns: "shared" })}
        </SheetTitle>
        <Tooltip content={closeLabel}>
          <SheetClose asChild>
            <Button
              type="button"
              iconOnly
              size="small"
              color="default"
              variant="text"
              className="shrink-0"
              aria-label={closeLabel}
              icon={<Outlined.Close aria-hidden />}
            />
          </SheetClose>
        </Tooltip>
      </SheetHeader>
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 pt-5 pb-[calc(20px+env(safe-area-inset-bottom))] min-[576px]:pb-5">
        {!enabled ? (
          <KnowledgeScopeUnavailable size="panel" />
        ) : query.isError ? (
          <Button variant="outline" onClick={() => void query.refetch()}>
            {t("retry")}
          </Button>
        ) : query.data && !data ? (
          <KnowledgeScopeUnavailable size="panel" role="alert" />
        ) : !data ? (
          <LoadingState label={t("loading")} className="min-h-32" />
        ) : (
          <>
            {isManagement ? (
              <dl className={`mb-4 flex flex-wrap gap-x-6 gap-y-3 ${styles.summary}`}>
                <div className="min-w-0 flex-1">
                  <dt className={`mb-1 ${styles.fieldLabel}`}>
                    {t("f118.document_code")}
                  </dt>
                  <dd className={`break-words ${styles.summaryValue}`}>{data.doc_code ?? "--"}</dd>
                </div>
                {data.current_primary_version_no !== null && (
                  <div className="min-w-0 flex-1">
                    <dt className={`mb-1 ${styles.fieldLabel}`}>
                      {t("f118.primary_version")}
                    </dt>
                    <dd className={styles.summaryValue}>{data.current_primary_version_no}</dd>
                  </div>
                )}
              </dl>
            ) : (
              <VersionHistorySummary
                documentTitle={data.title}
                documentCode={data.doc_code}
                primaryVersion={data.current_primary_version_no}
              />
            )}
            {operationsEnabled && (
              <div className="mb-4 space-y-3">
                <div className="flex flex-wrap gap-2">
                  {canUploadVersion && <Button
                    size="medium"
                    variant="solid"
                    disabled={busy || uncertain}
                    onClick={() =>
                      setPanel(panel === "upload" ? null : "upload")
                    }
                  >
                    {t("versions.new_version")}
                  </Button>}
                  <Button
                    size="medium"
                    variant="outlined"
                    color="default"
                    disabled={busy || uncertain}
                    onClick={() => setPanel(panel === "merge" ? null : "merge")}
                  >
                    {t("versions.merge")}
                  </Button>
                  {hasSimilar && (
                    <Button
                      size="medium"
                      variant="text"
                      color="default"
                      disabled={busy || uncertain}
                      onClick={() =>
                        onSimilar()
                      }
                    >
                      {t("versions.similar")}
                    </Button>
                  )}
                </div>
                {uncertain && (
                  <p role="alert" className="text-sm">
                    {t("versions.uncertain")}
                  </p>
                )}
                {panel === "upload" && canUploadVersion && (
                  <SpaceVersionUploadPanel
                    scope={scope}
                    spaceId={spaceId}
                    parentId={parentId}
                    documentId={data.document_id}
                    api={api}
                    onChanged={handleChanged}
                    onBusyChange={setBusy}
                  />
                )}
                {panel === "merge" && (
                  <SpaceVersionRelationPanel
                    scope={scope}
                    spaceId={spaceId}
                    fileId={fileId!}
                    mode="merge"
                    api={api}
                    onChanged={handleChanged}
                    onBusyChange={setBusy}
                  />
                )}
              </div>
            )}
            {data.versions.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                {t("f118.no_visible_versions")}
              </p>
            ) : (
              <VersionHistoryTable compact rows={data.versions.map((version) => ({
                id: version.version_id,
                versionNumber: version.version_no,
                isPrimary: version.is_primary,
                fileName: version.original_file_name,
                fileCode: version.file_code,
                uploader: version.uploader_name,
                uploadedAt: version.upload_time,
                status: version.status !== null && FILE_STATUSES[version.status] ? (
                  <StatusIndicator
                    status={version.status}
                    badge={<VersionHistoryStatusBadge status={version.status} />}
                  />
                ) : null,
                actions: (
                  <>
                    {operationsEnabled && !version.is_primary && (
                      <>
                        {version.status === 2 && (
                          <VersionHistoryAction
                            label={t("versions.set_primary")}
                            tone="primary"
                            disabled={busy || uncertain}
                            onClick={() => handleMutation(version.version_id, "primary")}
                          >
                            <CheckCircle className="size-4" aria-hidden />
                          </VersionHistoryAction>
                        )}
                        {canDeleteVersion(version.version_id) && (
                          <VersionHistoryAction
                            label={t("versions.delete_history")}
                            tone="danger"
                            disabled={busy || uncertain}
                            onClick={() => handleMutation(version.version_id, "delete")}
                          >
                            <Trash2 className="size-4" aria-hidden />
                          </VersionHistoryAction>
                        )}
                      </>
                    )}
                    <SpaceFileTools
                      scope={scope}
                      spaceId={spaceId}
                      fileId={version.knowledge_file_id}
                      status={version.status}
                    />
                  </>
                ),
              }))} />
            )}
          </>
        )}
      </div>
    </SheetContent>
  );
}
