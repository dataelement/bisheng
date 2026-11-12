import { Button, Tag } from "@bisheng/ui";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useContext, useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Sheet,
  SheetContent,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/bs-ui/sheet";
import {
  knowledgeVersionsApi,
  type KnowledgeVersionsApi,
} from "@/controllers/API/knowledgeVersions";
import {
  knowledgeQueryKeys,
  type KnowledgeQueryScope,
} from "@/controllers/hooks/knowledge";
import { showApiError } from "@/controllers/request";
import { locationContext } from "@/contexts/locationContext";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { SpaceVersionRelationPanel } from "./SpaceVersionRelationPanel";
import { SpaceVersionUploadPanel } from "./SpaceVersionUploadPanel";
import { SpaceSimilarDocumentPanel } from "./SpaceSimilarDocumentPanel";
import { SpaceFileTools } from "./SpaceFileTools";
import { FILE_STATUSES, StatusIndicator } from "./KnowledgeFileStatus";

interface SpaceVersionHistorySheetProps {
  scope: KnowledgeQueryScope;
  spaceId: number;
  parentId: number | null;
  fileId: number | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  hasSimilar?: boolean;
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
  return (
    <Sheet open={props.open} onOpenChange={props.onOpenChange}>
      {props.open && <HistoryContent key={targetKey} {...props} />}
    </Sheet>
  );
}

function HistoryContent({
  scope,
  spaceId,
  parentId,
  fileId,
  onOpenChange,
  hasSimilar = false,
  api: customApi,
}: SpaceVersionHistorySheetProps) {
  const { t } = useTranslation("knowledge");
  const { appConfig } = useContext(locationContext);
  const api = { ...knowledgeVersionsApi, ...customApi };
  const client = useQueryClient();
  const [panel, setPanel] = useState<"upload" | "merge" | "similar" | null>(
    null,
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
  const operationsEnabled =
    appConfig.versionManagementEnabled === true && enabled && !!data;
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
      aria-describedby={undefined}
      className="flex w-full flex-col gap-0 sm:max-w-[400px]"
    >
      <SheetHeader className="h-[60px] shrink-0 justify-center border-b px-6 pr-12">
        <SheetTitle className="m-0 truncate text-lg font-medium">
          {data?.title ?? t("f118.version_history")}
        </SheetTitle>
      </SheetHeader>
      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
        {!enabled ? (
          <p className="text-sm text-muted-foreground">
            {t("f118.scope_unavailable")}
          </p>
        ) : query.isError ? (
          <Button variant="outline" onClick={() => void query.refetch()}>
            {t("retry")}
          </Button>
        ) : query.data && !data ? (
          <p role="alert">{t("f118.scope_unavailable")}</p>
        ) : !data ? (
          <p className="text-sm text-muted-foreground" role="status">
            {t("loading")}
          </p>
        ) : (
          <>
            <dl className="mb-4 space-y-2 text-sm">
              <div>
                <dt className="text-muted-foreground">
                  {t("f118.document_code")}
                </dt>
                <dd>{data.doc_code ?? "--"}</dd>
              </div>
              {data.current_primary_version_no !== null && (
                <div>
                  <dt className="text-muted-foreground">
                    {t("f118.primary_version")}
                  </dt>
                  <dd>{data.current_primary_version_no}</dd>
                </div>
              )}
            </dl>
            {operationsEnabled && (
              <div className="mb-4 space-y-3">
                <div className="flex flex-wrap gap-2">
                  <Button
                    size="small"
                    variant="outlined"
                    disabled={busy || uncertain}
                    onClick={() =>
                      setPanel(panel === "upload" ? null : "upload")
                    }
                  >
                    {t("versions.new_version")}
                  </Button>
                  <Button
                    size="small"
                    variant="outlined"
                    disabled={busy || uncertain}
                    onClick={() => setPanel(panel === "merge" ? null : "merge")}
                  >
                    {t("versions.merge")}
                  </Button>
                  {hasSimilar && (
                    <Button
                      size="small"
                      variant="outlined"
                      disabled={busy || uncertain}
                      onClick={() =>
                        setPanel(panel === "similar" ? null : "similar")
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
                {panel === "upload" && (
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
                {panel === "similar" && (
                  <SpaceSimilarDocumentPanel
                    scope={scope}
                    spaceId={spaceId}
                    fileId={fileId!}
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
              <ol className="divide-y">
                {data.versions.map((version) => (
                  <li
                    key={version.version_id}
                    className="space-y-3 py-4 first:pt-0"
                  >
                    <div className="flex items-center gap-2 text-sm font-medium">
                      <span>
                        {t("f118.version_no")} {version.version_no}
                      </span>
                      {version.is_primary && (
                        <Tag size="small" color="brand">
                          {t("f118.primary_version")}
                        </Tag>
                      )}
                    </div>
                    <dl className="space-y-2 text-sm">
                      <div>
                        <dt className="text-muted-foreground">
                          {t("fileName")}
                        </dt>
                        <dd className="break-words">
                          {version.original_file_name}
                        </dd>
                      </div>
                      <div>
                        <dt className="text-muted-foreground">
                          {t("f118.document_code")}
                        </dt>
                        <dd>{version.file_code ?? "--"}</dd>
                      </div>
                      <div>
                        <dt className="text-muted-foreground">
                          {t("f118.version_uploader")}
                        </dt>
                        <dd>{version.uploader_name ?? "--"}</dd>
                      </div>
                      <div>
                        <dt className="text-muted-foreground">
                          {t("f118.version_upload_time")}
                        </dt>
                        <dd>
                          {version.upload_time?.replace("T", " ") ?? "--"}
                        </dd>
                      </div>
                      <div>
                        <dt className="mb-1 text-muted-foreground">
                          {t("status")}
                        </dt>
                        <dd>
                          {version.status !== null &&
                          FILE_STATUSES[version.status] ? (
                            <StatusIndicator status={version.status} />
                          ) : (
                            "--"
                          )}
                        </dd>
                      </div>
                    </dl>
                    {operationsEnabled && !version.is_primary && (
                      <div className="flex flex-wrap gap-2">
                        {version.status === 2 && (
                          <Button
                            size="small"
                            variant="outlined"
                            disabled={busy || uncertain}
                            onClick={() =>
                              handleMutation(version.version_id, "primary")
                            }
                          >
                            {t("versions.set_primary")}
                          </Button>
                        )}
                        <Button
                          size="small"
                          color="danger"
                          variant="text"
                          disabled={busy || uncertain}
                          onClick={() =>
                            handleMutation(version.version_id, "delete")
                          }
                        >
                          {t("versions.delete_history")}
                        </Button>
                      </div>
                    )}
                    <SpaceFileTools
                      scope={scope}
                      spaceId={spaceId}
                      fileId={version.knowledge_file_id}
                      status={version.status}
                    />
                  </li>
                ))}
              </ol>
            )}
          </>
        )}
      </div>
      <SheetFooter className="h-[60px] shrink-0 items-center border-t px-6">
        <Button variant="outline" onClick={() => onOpenChange(false)}>
          {t("close", { ns: "bs" })}
        </Button>
      </SheetFooter>
    </SheetContent>
  );
}
