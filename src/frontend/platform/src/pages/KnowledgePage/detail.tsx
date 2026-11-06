import { Breadcrumb, Button } from "@bisheng/ui";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useId } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  knowledgeSpaceApi,
  type KnowledgeSpaceInfo,
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
import { useKnowledgePageScope } from "@/hooks/useKnowledgePageScope";
import Files from "./components/Files";
import Header from "./components/Header";

const parseId = (value: string | null | undefined): number | null => {
  if (!value || !/^\d+$/.test(value)) return null;
  const id = Number(value);
  return Number.isSafeInteger(id) && id > 0 ? id : null;
};

interface SpaceDetailProps {
  scope: KnowledgeQueryScope;
  spaceId: number;
  parentId: number | null;
  onOpenFolder: (id: number | null) => void;
}

function SpaceDetail({
  scope,
  spaceId,
  parentId,
  onOpenFolder,
}: SpaceDetailProps) {
  const { t } = useTranslation("knowledge");
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
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

  return (
    <div className="relative size-full bg-background-login px-2">
      <div className="pt-4">
        <Header
          fileTitle
          title={title}
          description={parentId === null ? (info?.description ?? "") : ""}
          onBack={() => navigate("/filelib")}
        />
      </div>
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
      />
    </div>
  );
}

export default function FilesPage() {
  const { t } = useTranslation("knowledge");
  const { id } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const { scopes, isLoading, retry } = useKnowledgePageScope();
  const spaceId = parseId(id);
  const values = searchParams.getAll("parent_id");
  const parentId =
    values.length === 0
      ? null
      : values.length === 1
        ? parseId(values[0])
        : null;
  const invalidParent =
    values.length > 0 && (values.length !== 1 || parentId === null);
  if (spaceId === null || invalidParent)
    return <div role="status">{t("f118.scope_unavailable")}</div>;
  if (isLoading) return <div role="status">{t("f118.loading_directory")}</div>;
  if (!scopes)
    return (
      <div>
        <div role="status">{t("f118.scope_unavailable")}</div>
        <Button
          variant="text"
          onClick={() => {
            void retry();
          }}
        >
          {t("retry")}
        </Button>
      </div>
    );
  const scope = scopes.ordinary;
  const handleOpenFolder = (folderId: number | null) => {
    const next = new URLSearchParams(searchParams);
    if (folderId === null) next.delete("parent_id");
    else next.set("parent_id", String(folderId));
    setSearchParams(next);
  };
  return (
    <SpaceDetail
      key={JSON.stringify([
        scope.identityKey,
        scope.tenantId,
        scope.managementTenantId,
        scope.view,
        spaceId,
        parentId,
      ])}
      scope={scope}
      spaceId={spaceId}
      parentId={parentId}
      onOpenFolder={handleOpenFolder}
    />
  );
}
