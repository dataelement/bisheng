import { Button, Tag, Tooltip } from "@bisheng/ui";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Outlined } from "bisheng-icons";
import { useContext, useEffect, useId, useRef, useState } from "react";
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
  hasSimilar = false,
  initialPanel = null,
  api: customApi,
}: SpaceVersionHistorySheetProps) {
  const { t } = useTranslation("knowledge");
  const closeLabel = t("close", { ns: "bs" });
  const { appConfig } = useContext(locationContext);
  const api = { ...knowledgeVersionsApi, ...customApi };
  const client = useQueryClient();
  const [panel, setPanel] = useState<"upload" | "merge" | "similar" | null>(
    initialPanel,
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
        <SheetTitle title={data?.title} className="m-0 min-w-0 truncate text-base font-medium text-text-1">
          {data?.title ?? t("f118.version_history")}
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
            <dl className="mb-4 grid grid-cols-2 gap-3 rounded-lg bg-fill-1 p-3 text-sm">
              <div>
                <dt className="text-muted-foreground">
                  {t("f118.document_code")}
                </dt>
                <dd className="break-words">{data.doc_code ?? "--"}</dd>
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
                    size="medium"
                    disabled={busy || uncertain}
                    onClick={() =>
                      setPanel(panel === "upload" ? null : "upload")
                    }
                  >
                    {t("versions.new_version")}
                  </Button>
                  <Button
                    size="medium"
                    color="default"
                    variant="outlined"
                    disabled={busy || uncertain}
                    onClick={() => setPanel(panel === "merge" ? null : "merge")}
                  >
                    {t("versions.merge")}
                  </Button>
                  {hasSimilar && (
                    <Button
                      size="medium"
                      color="default"
                      variant="text"
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
              <ol className="divide-y divide-border-base border-t border-border-base">
                {data.versions.map((version) => (
                  <li
                    key={version.version_id}
                    className="space-y-3 py-4 last:pb-0"
                  >
                    <div className="flex flex-wrap items-center gap-2 text-sm font-medium text-text-1">
                      <span>
                        {t("f118.version_no")} {version.version_no}
                      </span>
                      {version.is_primary && (
                        <Tag size="small" color="brand">
                          {t("f118.primary_version")}
                        </Tag>
                      )}
                      {version.status !== null && FILE_STATUSES[version.status] && (
                        <StatusIndicator status={version.status} />
                      )}
                    </div>
                    <dl className="grid grid-cols-2 gap-x-3 gap-y-2 break-words text-sm">
                      <div className="col-span-2 min-w-0">
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
                      {(version.status === null || !FILE_STATUSES[version.status]) && (
                        <div>
                          <dt className="text-muted-foreground">{t("status")}</dt>
                          <dd>--</dd>
                        </div>
                      )}
                    </dl>
                    <div className="flex flex-wrap items-center gap-2">
                      {operationsEnabled && !version.is_primary && (
                        <>
                          {version.status === 2 && (
                            <Button
                              color="default"
                              variant="text"
                              disabled={busy || uncertain}
                              onClick={() =>
                                handleMutation(version.version_id, "primary")
                              }
                            >
                              {t("versions.set_primary")}
                            </Button>
                          )}
                          <Button
                            color="danger"
                            variant="text"
                            disabled={busy || uncertain}
                            onClick={() =>
                              handleMutation(version.version_id, "delete")
                            }
                          >
                            {t("versions.delete_history")}
                          </Button>
                        </>
                      )}
                      <SpaceFileTools
                        scope={scope}
                        spaceId={spaceId}
                        fileId={version.knowledge_file_id}
                        status={version.status}
                      />
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </>
        )}
      </div>
    </SheetContent>
  );
}
