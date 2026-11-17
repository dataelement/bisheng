import { Breadcrumb, Button, toast } from "@bisheng/ui";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { isErrorEnvelope } from "@bisheng/api-client";
import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  knowledgeSpaceApi,
  type KnowledgeSpaceInfo,
  type KnowledgeSpaceChild,
} from "@/controllers/API/knowledgeSpace";
import {
  knowledgeFilesApi,
  type SpaceFolderParent,
} from "@/controllers/API/knowledgeFiles";
import {
  knowledgeQueryKeys,
  type KnowledgeQueryScope,
} from "@/controllers/hooks/knowledge";
import { showApiError } from "@/controllers/request";
import Files from "./components/Files";
import Header from "./components/Header";
import { SpaceManagementView } from "./components/SpaceManagementView";
import { SpaceFileDetail } from "./components/SpaceFileDetail";
import { SpaceProcessingPanel } from "./components/SpaceProcessingDialog";
import { useSpaceCopyTasks } from "./useSpaceCopyTasks";
import { SpaceCopyStatus } from "./components/SpaceCopyStatus";

export const parseKnowledgeId = (value: string | null | undefined): number | null => {
  if (!value || !/^\d+$/.test(value)) return null;
  const id = Number(value);
  return Number.isSafeInteger(id) && id > 0 ? id : null;
};

interface SpaceDetailProps {
  scope: KnowledgeQueryScope;
  spaceId: number;
  parentId: number | null;
  onOpenFolder: (id: number | null) => void;
  presentation?: "workspace";
}

export function SpaceDetail({
  scope,
  spaceId,
  parentId,
  onOpenFolder,
  presentation,
}: SpaceDetailProps) {
  const { t } = useTranslation("knowledge");
  const client = useQueryClient();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const fileParams = searchParams.getAll("file_id");
  const fileId = fileParams.length === 1 ? parseKnowledgeId(fileParams[0]) : null;
  const [openedFile, setOpenedFile] = useState<KnowledgeSpaceChild | undefined>();
  const fileStatus =
    searchParams.get("fileStatus") === "abnormal" ? "abnormal" : "all";
  const instance = useId();
  const copyTasks = useSpaceCopyTasks(scope);
  const copyTask = copyTasks.data?.find((task) => task.id === spaceId);
  const watchedCopy = useRef<number | null>(null);
  const facts = useQuery<KnowledgeSpaceInfo | SpaceFolderParent[]>({
    queryKey: [
      ...knowledgeQueryKeys.space(scope, spaceId),
      "directory-header",
      instance,
      parentId,
    ],
    queryFn: () =>
      parentId === null
        ? knowledgeSpaceApi.getSpaceInfo(spaceId)
        : knowledgeFilesApi.listSpaceFolderParents(spaceId, parentId),
    enabled: fileParams.length === 0 && !copyTasks.isInitialLoading && !copyTask,
    keepPreviousData: false,
    cacheTime: 0,
  });
  useEffect(() => {
    if (facts.error) showApiError(facts.error);
  }, [facts.error]);
  const info = !Array.isArray(facts.data) ? facts.data : undefined;
  useEffect(() => {
    if (copyTask) watchedCopy.current = spaceId;
    else if (copyTasks.isSuccess && info?.state === 1 && watchedCopy.current === spaceId) {
      watchedCopy.current = null;
      toast.show({ type: "success", message: t("space_copy_ui.created", { name: info.name }) });
    }
  }, [copyTask, copyTasks.isSuccess, info, spaceId, t]);
  const parents = Array.isArray(facts.data) ? facts.data : [];
  const showCopyRecovery = parentId === null && (
    info?.state === 0 || info?.state === 2 ||
    (isErrorEnvelope(facts.error) && facts.error.status_code === 25008)
  );
  const title =
    parentId === null
      ? (info?.name ?? "")
      : String(parents[parents.length - 1]?.file_name ?? "");

  const directory = (toolbarTarget?: HTMLDivElement | null) => (
    <>
      {parentId !== null && parents.length > 0 && (
        <div className={presentation === "workspace" ? "shrink-0 px-4 py-2" : undefined}>
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
        </div>
      )}
      {facts.isInitialLoading && (
        <div role="status" className={presentation === "workspace" ? "px-4" : undefined}>{t("f118.loading_directory")}</div>
      )}
      {facts.isError && (
        <Button
          variant="text"
          className={presentation === "workspace" ? "mx-4 self-start" : undefined}
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
              void client.invalidateQueries({ queryKey: knowledgeQueryKeys.scope(scope) });
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
        onOpenFile={presentation === "workspace" ? (item) => {
          setOpenedFile(item);
          const next = new URLSearchParams(searchParams);
          next.set("file_id", String(item.id));
          setSearchParams(next);
        } : undefined}
      />
    </>
  );
  if (copyTask) return <SpaceCopyStatus key={copyTask.job_id} scope={scope} task={copyTask} onCompleted={() => {
    void client.invalidateQueries({ queryKey: knowledgeQueryKeys.scope(scope) });
  }} />;
  if (copyTasks.isInitialLoading) return <p role="status">{t("f118.loading_directory")}</p>;
  if (fileParams.length > 0 && fileId === null) return <p role="status">{t("f118.scope_unavailable")}</p>;
  if (presentation === "workspace" && fileId !== null) return (
    <div className="h-full min-h-0 px-4">
      <SpaceFileDetail
        key={JSON.stringify([scope, spaceId, fileId])} scope={scope} spaceId={spaceId} fileId={fileId}
        initialFile={openedFile?.id === fileId ? openedFile : undefined}
        onBack={() => { const next = new URLSearchParams(searchParams); next.delete("file_id"); setSearchParams(next); }}
      />
    </div>
  );
  if (presentation === "workspace") return (
    <SpaceManagementView scope={scope} spaceId={spaceId} parentId={parentId} title={title} description={parentId === null ? info?.description ?? "" : ""}>
      {(toolbarTarget) => directory(toolbarTarget)}
    </SpaceManagementView>
  );
  return <div className="relative size-full bg-background-login px-2">
    <div className="pt-4"><Header fileTitle title={title} description={info?.description ?? ""} onBack={() => navigate("/filelib")} /></div>
    {directory()}
  </div>;
}
