import { Button } from "@bisheng/ui";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useId } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { getMyResourcePermissionsApi } from "@/controllers/API/permission";
import {
  knowledgeQueryKeys,
  type KnowledgeQueryScope,
} from "@/controllers/hooks/knowledge";
import { showApiError } from "@/controllers/request";
import { useKnowledgePageScope } from "@/hooks/useKnowledgePageScope";
import { SpaceFileUploadPanel } from "./components/SpaceFileUploadPanel";

const parseId = (value: string | null | undefined): number | null => {
  if (!value || !/^\d+$/.test(value)) return null;
  const id = Number(value);
  return Number.isSafeInteger(id) && id > 0 ? id : null;
};
interface UploadTargetProps {
  scope: KnowledgeQueryScope;
  spaceId: number;
  parentId: number | null;
}
function UploadTarget({ scope, spaceId, parentId }: UploadTargetProps) {
  const { t } = useTranslation("knowledge");
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const instance = useId();
  const permissions = useQuery({
    queryKey: [
      ...knowledgeQueryKeys.space(scope, spaceId),
      "upload-target",
      instance,
      parentId,
    ],
    queryFn: () =>
      getMyResourcePermissionsApi(
        parentId === null ? "knowledge_space" : "folder",
        String(parentId ?? spaceId),
      ),
    retry: false,
    cacheTime: 0,
  });
  useEffect(() => {
    if (permissions.error) showApiError(permissions.error);
  }, [permissions.error]);
  return (
    <div className="space-y-4 p-4">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">{t("uploadFile")}</h1>
        <Button
          variant="link"
          onClick={() =>
            navigate({
              pathname: `/filelib/${spaceId}`,
              search: params.toString(),
            })
          }
        >
          {t("back")}
        </Button>
      </div>
      {permissions.isInitialLoading ? (
        <div role="status">{t("f118.loading_directory")}</div>
      ) : permissions.isError ? (
        <Button
          variant="outlined"
          onClick={() => {
            void permissions.refetch();
          }}
        >
          {t("retry")}
        </Button>
      ) : permissions.data?.actions.includes("upload_file") ? (
        <SpaceFileUploadPanel
          scope={scope}
          spaceId={spaceId}
          parentId={parentId}
        />
      ) : (
        <div role="status">{t("noOperationPermission")}</div>
      )}
    </div>
  );
}

export function FilesUpload() {
  const { t } = useTranslation("knowledge");
  const { id } = useParams();
  const [params] = useSearchParams();
  const { scopes, isLoading, canManage, retry } = useKnowledgePageScope();
  const spaceId = parseId(id);
  const parents = params.getAll("parent_id");
  const parentId = parents.length === 1 ? parseId(parents[0]) : null;
  if (
    spaceId === null ||
    (parents.length > 0 && (parents.length !== 1 || parentId === null))
  )
    return <div role="status">{t("f118.scope_unavailable")}</div>;
  if (isLoading) return <div role="status">{t("f118.loading_directory")}</div>;
  if (!scopes)
    return (
      <div>
        <div role="status">{t("f118.scope_unavailable")}</div>
        <Button
          variant="outlined"
          onClick={() => {
            void retry();
          }}
        >
          {t("retry")}
        </Button>
      </div>
    );
  const views = params.getAll("view");
  const scope = canManage && views.length === 1 && views[0] === "admin" ? scopes.admin : scopes.ordinary;
  return (
    <UploadTarget
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
    />
  );
}

export default FilesUpload;
