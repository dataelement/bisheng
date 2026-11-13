import { Breadcrumb, Button } from "@bisheng/ui";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useId, useState } from "react";
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
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const fileParams = searchParams.getAll("file_id");
  const fileId = fileParams.length === 1 ? parseKnowledgeId(fileParams[0]) : null;
  const [openedFile, setOpenedFile] = useState<KnowledgeSpaceChild | undefined>();
  const fileStatus =
    searchParams.get("fileStatus") === "abnormal" ? "abnormal" : "all";
  const instance = useId();
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
    enabled: fileParams.length === 0,
    keepPreviousData: false,
    cacheTime: 0,
  });
  useEffect(() => {
    if (facts.error) showApiError(facts.error);
  }, [facts.error]);
  const info = !Array.isArray(facts.data) ? facts.data : undefined;
  const parents = Array.isArray(facts.data) ? facts.data : [];
  const title =
    parentId === null
      ? (info?.name ?? "")
      : String(parents[parents.length - 1]?.file_name ?? "");

  const directory = (toolbarTarget?: HTMLDivElement | null) => (
    <>
      {parentId !== null && parents.length > 0 && (
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
      {facts.isInitialLoading && (
        <div role="status">{t("f118.loading_directory")}</div>
      )}
      {facts.isError && (
        <Button
          variant="text"
          onClick={() => {
            void facts.refetch();
          }}
        >
          {t("retry")}
        </Button>
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
  if (fileParams.length > 0 && fileId === null) return <p role="status">{t("f118.scope_unavailable")}</p>;
  if (presentation === "workspace" && fileId !== null) return <SpaceFileDetail
    key={JSON.stringify([scope, spaceId, fileId])} scope={scope} spaceId={spaceId} fileId={fileId}
    initialFile={openedFile?.id === fileId ? openedFile : undefined}
    onBack={() => { const next = new URLSearchParams(searchParams); next.delete("file_id"); setSearchParams(next); }}
  />;
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
