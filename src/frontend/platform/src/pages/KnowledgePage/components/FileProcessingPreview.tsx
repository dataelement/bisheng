import { LoadingState } from "@/components/bs-icons/loading/LoadingState";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@bisheng/ui";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { knowledgeFilesApi } from "@/controllers/API/knowledgeFiles";
import type { FileMetadata } from "@/controllers/API/knowledgeIndex";
import type { ProcessingDefaults } from "@/controllers/API/knowledgeSpace";
import {
  knowledgeQueryKeys,
  type KnowledgeQueryScope,
} from "@/controllers/hooks/knowledge";
import { showApiError } from "@/controllers/request";
import PreviewResult from "./PreviewResult";
import { initialWizardStrategy } from "./uploadWizardRules";
import { fileRuleScope } from "./fileProcessingRules";

interface FileProcessingPreviewProps {
  scope: KnowledgeQueryScope;
  spaceId: number;
  fileId: number;
  file: FileMetadata;
  defaults: ProcessingDefaults;
  onReady: (ready: boolean) => void;
}
export function FileProcessingPreview({
  scope,
  spaceId,
  fileId,
  file,
  defaults,
  onReady,
}: FileProcessingPreviewProps) {
  const { t } = useTranslation("knowledge");
  const [previewCount, setPreviewCount] = useState(0);
  const [previewFailed, setPreviewFailed] = useState(false);
  const handlePreviewResult = (ready: boolean) => {
    setPreviewFailed(!ready);
    onReady(ready);
  };
  const handleRetry = () => {
    setPreviewFailed(false);
    onReady(false);
    setPreviewCount((count) => count + 1);
  };
  const preview = useQuery({
    queryKey: [
      ...knowledgeQueryKeys.space(scope, spaceId),
      "processing-preview",
      fileId,
    ],
    queryFn: () => knowledgeFilesApi.getSpaceFilePreview(spaceId, fileId),
    retry: false,
    cacheTime: 0,
  });
  useEffect(() => {
    if (preview.error) showApiError(preview.error);
  }, [preview.error]);
  if (!preview.data)
    return preview.isError ? (
      <p role="alert">{t("f118.load_failed")}</p>
    ) : (
      <LoadingState label={t("f118.loading_space")} className="min-h-32" />
    );
  const strategy = initialWizardStrategy(defaults, spaceId, [
    {
      id: String(fileId),
      fileName: file.file_name ?? String(fileId),
      file_path: preview.data.original_url,
      suffix: file.file_name?.split(".").pop()?.toLowerCase() ?? "txt",
      fileType: fileRuleScope(file) === "table" ? "table" : "file",
      split_rule: {},
    },
  ]);
  const rules = {
    ...strategy.rules,
    fileList: strategy.rules.fileList.map((item) => ({
      ...item,
      previewFileId: fileId,
      originalUrl: preview.data.original_url,
    })),
  };
  return (
    <>
      {previewFailed && (
        <Button variant="outlined" onClick={handleRetry}>
          {t("retry")}
        </Button>
      )}
      <div className="h-[60vh] min-h-80">
        <PreviewResult
          rules={rules}
          step={3}
          previewCount={previewCount}
          applyEachCell={false}
          cellGeneralConfig={strategy.cellGeneralConfig}
          kId={spaceId}
          editable={false}
          handlePreviewResult={handlePreviewResult}
        />
      </div>
    </>
  );
}
