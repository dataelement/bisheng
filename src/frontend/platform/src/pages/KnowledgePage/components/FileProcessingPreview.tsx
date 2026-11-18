import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
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
    return (
      <p role="status">
        {t(preview.isError ? "f118.load_failed" : "f118.loading_space")}
      </p>
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
  return (
    <div className="h-[60vh] min-h-80">
      <PreviewResult
        rules={strategy.rules}
        step={3}
        previewCount={0}
        applyEachCell={false}
        cellGeneralConfig={strategy.cellGeneralConfig}
        kId={spaceId}
        editable={false}
        handlePreviewResult={onReady}
      />
    </div>
  );
}
