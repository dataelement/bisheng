import { Button } from "@bisheng/ui";
import { useTranslation } from "react-i18next";
import type { KnowledgeQueryScope } from "@/controllers/hooks/knowledge";
import { useSpaceMetadataSchema } from "../hooks/useSpaceMetadataSchema";
import { MetadataManagementDialog } from "./MetadataManagementDialog";
import { SpaceProcessingProgress } from "./SpaceProcessingProgress";
interface SpaceMetadataPanelProps {
  scope: KnowledgeQueryScope;
  spaceId: number;
  onClose: () => void;
}
export function SpaceMetadataPanel(props: SpaceMetadataPanelProps) {
  return <MetadataPanel key={JSON.stringify([props.scope, props.spaceId])} {...props} />;
}
function MetadataPanel({ scope, spaceId, onClose }: SpaceMetadataPanelProps) {
  const { t } = useTranslation("knowledge");
  const { uncertain, schema, recentJobs, canEdit, mutations, jobId, jobState, handleStateChange, handleCompleted, refetch } = useSpaceMetadataSchema({ scope, spaceId });
  const schemaData = schema.data;
  return (
    <MetadataManagementDialog
      open
      id={String(spaceId)}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      initialMetadata={schemaData?.fields}
      hasManagePermission={canEdit}
      mutations={mutations}
      placeholder={schemaData ? undefined : (
        <div role={schema.isError ? "alert" : "status"} className="space-y-3">
          <p>{t(schema.isError ? "f118.load_failed" : "f118.loading_space")}</p>
          {schema.isError && (
            <Button onClick={() => { void refetch(); }}>
              {t("retry")}
            </Button>
          )}
        </div>
      )}
    >
      {uncertain && <p role="alert">{t("fileMetadata.uncertain")}</p>}
      {jobId && jobState !== "succeeded" && (
        <SpaceProcessingProgress
          key={jobId}
          scope={scope}
          spaceId={spaceId}
          jobId={jobId}
          kind="metadata_schema_change"
          onCompleted={handleCompleted}
          onStateChange={handleStateChange}
        />
      )}
      {!jobId && recentJobs.isError && (
        <div className="space-y-3" role="alert">
          <p>{t("detail.load_failed")}</p>
          <Button onClick={() => { void recentJobs.refetch(); }}>{t("retry")}</Button>
        </div>
      )}
    </MetadataManagementDialog>
  );
}
