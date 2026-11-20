import { Breadcrumb, Button, toast } from "@bisheng/ui";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { isErrorEnvelope } from "@bisheng/api-client";
import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  knowledgeSpaceApi,
  type KnowledgeSpaceChild,
} from "@/controllers/API/knowledgeSpace";
import {
  knowledgeQueryKeys,
  type KnowledgeQueryScope,
} from "@/controllers/hooks/knowledge";
import { showApiError } from "@/controllers/request";
import { LoadingState } from "@/components/bs-icons/loading/LoadingState";
import Files from "./components/Files";
import Header from "./components/Header";
import { KnowledgeScopeUnavailable } from "./components/KnowledgeScopeUnavailable";
import { SpaceManagementView } from "./components/SpaceManagementView";
import { SpaceFileDetail } from "./components/SpaceFileDetail";
import { SpaceProcessingPanel } from "./components/SpaceProcessingDialog";
import { useSpaceCopyTasks } from "./useSpaceCopyTasks";
import { SpaceCopyStatus } from "./components/SpaceCopyStatus";
import { useSpaceFolderPath } from "./hooks/useSpaceFolderPath";

export const parseKnowledgeId = (
  value: string | null | undefined,
): number | null => {
  if (!value || !/^\d+$/.test(value)) return null;
  const id = Number(value);
  return Number.isSafeInteger(id) && id > 0 ? id : null;
};

interface SpaceDetailProps {
  scope: KnowledgeQueryScope;
  spaceId: number;
  parentId: number | null;
  onOpenFolder: (id: number | null) => void;
  onDeleted?: (id: number) => void;
  presentation?: "workspace";
}

export function SpaceDetail({
  scope,
  spaceId,
  parentId,
  onOpenFolder,
  onDeleted,
  presentation,
}: SpaceDetailProps) {
  const { t } = useTranslation("knowledge");
  const client = useQueryClient();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const processingParams = searchParams.getAll("process_file_id");
  const processingFileId =
    processingParams.length === 1
      ? parseKnowledgeId(processingParams[0])
      : null;
  const fileParams = searchParams.getAll("file_id");
  const fileId =
    fileParams.length === 1 ? parseKnowledgeId(fileParams[0]) : null;
  const [openedFile, setOpenedFile] = useState<{
    parentId: number | null;
    item: KnowledgeSpaceChild;
  }>();
  const fileStatus =
    searchParams.get("fileStatus") === "abnormal" ? "abnormal" : "all";
  const instance = useId();
  const copyTasks = useSpaceCopyTasks(scope);
  const copyTask = copyTasks.data?.find((task) => task.id === spaceId);
  const watchedCopy = useRef<number | null>(null);
  const spaceInfo = useQuery({
    queryKey: [
      ...knowledgeQueryKeys.info(scope, spaceId),
      "directory-root",
      instance,
    ],
    queryFn: () =>
      knowledgeSpaceApi.getSpaceInfo(spaceId, { showError: false }),
    enabled:
      parentId === null &&
      fileParams.length === 0 &&
      processingParams.length === 0 &&
      !copyTasks.isInitialLoading &&
      (!copyTask || copyTask.state === 1),
    keepPreviousData: false,
    cacheTime: 0,
  });
  // The sidebar reads the same path, including when the URL opens a file directly.
  const folderPath = useSpaceFolderPath(scope, spaceId, parentId);
  const facts = parentId === null ? spaceInfo : folderPath;
  const { error } = facts;
  const spaceMissing =
    parentId === null &&
    isErrorEnvelope(spaceInfo.error) &&
    spaceInfo.error.status_code === 18000;
  useEffect(() => {
    if (spaceMissing) onDeleted?.(spaceId);
  }, [spaceMissing, onDeleted, spaceId]);
  useEffect(() => {
    if (error && !spaceMissing) showApiError(error);
  }, [error, spaceMissing]);
  useEffect(() => {
    setOpenedFile(undefined);
  }, [parentId]);
  const info = spaceInfo.isError ? undefined : spaceInfo.data;
  useEffect(() => {
    if (copyTask) watchedCopy.current = spaceId;
    else if (
      copyTasks.isSuccess &&
      info?.state === 1 &&
      watchedCopy.current === spaceId
    ) {
      watchedCopy.current = null;
      toast.show({
        type: "success",
        message: t("space_copy_ui.created", { name: info.name }),
      });
    }
  }, [copyTask, copyTasks.isSuccess, info, spaceId, t]);
  const parents = folderPath.data ?? [];
  const showCopyRecovery =
    parentId === null &&
    (info?.state === 0 ||
      info?.state === 2 ||
      (isErrorEnvelope(facts.error) && facts.error.status_code === 25008));
  const title =
    parentId === null
      ? (info?.name ?? "")
      : String(parents[parents.length - 1]?.file_name ?? "");

  const directory = (toolbarTarget?: HTMLDivElement | null) => (
    <>
      {copyTask?.state === 1 && (
        <SpaceCopyStatus
          compact
          scope={scope}
          task={copyTask}
          onCompleted={() => {
            void client.invalidateQueries({
              queryKey: knowledgeQueryKeys.space(scope, spaceId),
            });
          }}
        />
      )}
      {presentation !== "workspace" &&
        parentId !== null &&
        parents.length > 0 && (
          <Breadcrumb
            ariaLabel={t("f118.current_folder")}
            expandLabel={(count) => t("f118.expand_folders", { count })}
            items={[
              {
                key: "space",
                title: t("f118.spaces"),
                onClick: () => onOpenFolder(null),
              },
              ...parents.map((folder) => ({
                key: String(folder.id),
                title: String(folder.file_name),
                onClick: () => onOpenFolder(folder.id),
              })),
            ]}
          />
        )}
      {facts.isError && (
        <Button
          variant="text"
          className={
            presentation === "workspace" ? "mx-4 self-start" : undefined
          }
          onClick={() => {
            void facts.refetch();
          }}
        >
          {t("retry")}
        </Button>
      )}
      {showCopyRecovery && (
        <div className={presentation === "workspace" ? "px-4" : undefined}>
          <p role="status">{t("space_copy_ui.recovery_notice")}</p>
          <SpaceProcessingPanel
            scope={scope}
            spaceId={spaceId}
            mode="jobs"
            jobKind="space_copy"
            onSaved={() => {
              void client.invalidateQueries({
                queryKey: knowledgeQueryKeys.scope(scope),
              });
            }}
          />
        </div>
      )}
      <Files
        key={fileStatus}
        scope={scope}
        spaceId={spaceId}
        parentId={parentId}
        onOpenFolder={onOpenFolder}
        presentation={presentation}
        toolbarTarget={toolbarTarget}
        onOpenFile={
          presentation === "workspace"
            ? (item) => {
                setOpenedFile({ parentId, item });
                const next = new URLSearchParams(searchParams);
                next.set("file_id", String(item.id));
                setSearchParams(next);
              }
            : undefined
        }
      />
    </>
  );
  if (copyTask && copyTask.state !== 1)
    return (
      <SpaceCopyStatus
        key={copyTask.job_id}
        scope={scope}
        task={copyTask}
        onCompleted={() => {
          void client.invalidateQueries({
            queryKey: knowledgeQueryKeys.scope(scope),
          });
        }}
      />
    );
  if (copyTasks.isInitialLoading)
    return <LoadingState size="page" className="h-full" label={t("f118.loading_directory")} />;
  if ((fileParams.length > 0 && fileId === null) || (processingParams.length > 0 && processingFileId === null))
    return <KnowledgeScopeUnavailable />;
  if (processingFileId !== null)
    return (
      <div className="h-full overflow-auto px-4">
        <SpaceProcessingPanel
          key={JSON.stringify([scope, spaceId, processingFileId])}
          scope={scope}
          spaceId={spaceId}
          fileId={processingFileId}
          mode="file"
          onBack={() => {
            const next = new URLSearchParams(searchParams);
            next.delete("process_file_id");
            setSearchParams(next);
          }}
          onSaved={() => {
            void client.invalidateQueries({
              queryKey: knowledgeQueryKeys.space(scope, spaceId),
            });
          }}
        />
      </div>
    );
  if (presentation === "workspace" && fileId !== null)
    return (
      <div className="h-full min-h-0 px-4">
        <SpaceFileDetail
          key={JSON.stringify([scope, spaceId, parentId, fileId])}
          scope={scope}
          spaceId={spaceId}
          fileId={fileId}
          onProcess={() => {
            const next = new URLSearchParams(searchParams);
            next.set("process_file_id", String(fileId));
            setSearchParams(next);
          }}
          initialFile={
            openedFile?.parentId === parentId && openedFile.item.id === fileId
              ? openedFile.item
              : undefined
          }
          onBack={() => {
            const next = new URLSearchParams(searchParams);
            next.delete("file_id");
            setSearchParams(next);
          }}
        />
      </div>
    );
  if (spaceMissing)
    return (
      <LoadingState size="page" className="h-full" label={t("sidebar.loading")} />
    );
  if (presentation === "workspace")
    return (
      <SpaceManagementView
        scope={scope}
        spaceId={spaceId}
        parentId={parentId}
        title={title}
        spaceInfo={info}
        folderPath={parentId === null ? undefined : { parents, onOpenFolder }}
        onDeleted={onDeleted}
      >
        {(toolbarTarget) => directory(toolbarTarget)}
      </SpaceManagementView>
    );
  return (
    <div className="relative size-full bg-background-login px-2">
      <div className="pt-4">
        <Header
          fileTitle
          title={title}
          description={info?.description ?? ""}
          onBack={() => navigate("/filelib")}
        />
      </div>
      {directory()}
    </div>
  );
}
