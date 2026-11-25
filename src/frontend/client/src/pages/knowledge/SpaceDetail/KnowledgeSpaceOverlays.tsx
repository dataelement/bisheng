import { FileType } from "~/api/knowledge";
import { getFileDownloadApi } from "~/api/knowledge";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
} from "~/components/ui";
import { triggerUrlDownload } from "../knowledgeUtils";
import { EditTagsModal } from "./EditTagsModal";
import { KnowledgeSpaceShareDialog } from "./KnowledgeSpaceShareDialog";
import { MoveJobProgress } from "./MoveJobProgress";
import { MoveToDialog } from "./MoveToDialog";
import { VersionManagementDialog } from "./VersionManagementDialog";
import { VersionHistorySheet } from "./VersionHistorySheet";
import { SimilarDocumentDialog } from "./SimilarDocumentDialog";
import { knowledgeUploadCapabilities } from "../knowledgeUploadCapabilities";
import type { KnowledgeSpaceModel } from "./index";
interface KnowledgeSpaceOverlaysProps {
  model: KnowledgeSpaceModel;
}
export function KnowledgeSpaceOverlays({ model }: KnowledgeSpaceOverlaysProps) {
  const {
    localize,
    displayFiles,
    selectedFiles,
    editingTagsFileId,
    isBatchTagging,
    canEditSpace,
    canReadSpaceTags,
    versionManagementEnabled,
    spaceIdNum,
    versionMgmtFile,
    setVersionMgmtFile,
    versionHistoryFile,
    setVersionHistoryFile,
    similarDialogOpen,
    setSimilarDialogOpen,
    similarRestrictIds,
    setSimilarRestrictIds,
    handleVersionAction,
    permTarget,
    setPermTarget,
    showToast,
    webLinkDialogOpen,
    setWebLinkDialogOpen,
    webLinkUrl,
    setWebLinkUrl,
    webLinkTitle,
    setWebLinkTitle,
    webLinkSubmitting,
    resetWebLinkDialog,
    submitWebLink,
    moveConfirmation,
    moveProgress,
    moveDialogOpen,
    setMoveDialogOpen,
    handleMoveConfirm,
    handlePreviewFile,
    handleCloseEditTags,
    handleTagsSaved,
    space,
  } = model;
  return (
    <>
      {" "}
      {/* Edit Tags Modal */}
      <EditTagsModal
        tagScope={model.providerUploads.tagScope}
        canEditFileTags={!!editingTagsFileId && model.renameEntryIds.has(editingTagsFileId)}
        canManageSpaceTags={canEditSpace}
        canReadSpaceTags={canReadSpaceTags}
        isOpen={!!editingTagsFileId || isBatchTagging}
        onClose={handleCloseEditTags}
        onSaved={handleTagsSaved}
        onBatchSaved={model.handleBatchTagsSaved}
        availableTags={model.providerUploads.tagScope.kind !== 'native' ? undefined : displayFiles
          .filter((file) => selectedFiles.has(file.id))
          .flatMap((file) => file.tags ?? [])}
        spaceId={space.id}
        fileId={isBatchTagging ? null : editingTagsFileId}
        fileIds={isBatchTagging ? Array.from(selectedFiles) : undefined}
        batchItems={
          isBatchTagging
            ? displayFiles
                .filter((file) => selectedFiles.has(file.id))
                .map((file) => ({
                  id: Number(file.id),
                  type: file.type === FileType.FOLDER ? ("folder" as const) : ("file" as const),
                  name: file.name,
                }))
            : undefined
        }
        initialTagIds={
          model.providerUploads.tagScope.kind === 'native' && editingTagsFileId && !isBatchTagging
            ? displayFiles.find((f) => f.id === editingTagsFileId)?.tags?.map((t) => t.id) || []
            : []
        }
      />
      {model.canUploadNativeExtras && knowledgeUploadCapabilities.webLink && (
        <Dialog
          open={webLinkDialogOpen}
          onOpenChange={(open) => {
            setWebLinkDialogOpen(open);
            if (!open) resetWebLinkDialog();
          }}
        >
          <DialogContent className="max-w-[520px]">
            <DialogHeader>
              <DialogTitle>{localize("com_knowledge.web_link_import_title")}</DialogTitle>
            </DialogHeader>
            <div className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="knowledge-web-link-url">
                  {localize("com_knowledge.web_link_url")}
                </Label>
                <Input
                  id="knowledge-web-link-url"
                  value={webLinkUrl}
                  onChange={(e) => setWebLinkUrl(e.target.value)}
                  placeholder="https://example.com/article"
                  disabled={webLinkSubmitting}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="knowledge-web-link-title">
                  {localize("com_knowledge.web_link_title")}
                </Label>
                <Input
                  id="knowledge-web-link-title"
                  value={webLinkTitle}
                  onChange={(e) => setWebLinkTitle(e.target.value)}
                  placeholder={localize("com_knowledge.web_link_title_placeholder")}
                  disabled={webLinkSubmitting}
                />
              </div>
            </div>
            <DialogFooter>
              <button
                type="button"
                className="inline-flex h-9 items-center justify-center rounded-md border border-border-base bg-white px-4 text-sm text-text-2 hover:bg-fill-1"
                onClick={() => setWebLinkDialogOpen(false)}
                disabled={webLinkSubmitting}
              >
                {localize("com_knowledge.cancel")}
              </button>
              <button
                type="button"
                className="inline-flex h-9 items-center justify-center rounded-md bg-primary px-4 text-sm text-white hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-60"
                onClick={() => submitWebLink(false)}
                disabled={webLinkSubmitting}
              >
                {webLinkSubmitting
                  ? localize("com_knowledge.importing")
                  : localize("com_knowledge.import")}
              </button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
      {permTarget && (
        <KnowledgeSpaceShareDialog
          open={!!permTarget}
          onOpenChange={(open) => {
            if (!open) {
              setPermTarget(null);
            }
          }}
          resourceType={permTarget.type}
          resourceId={permTarget.id}
          resourceName={permTarget.name}
        />
      )}
      {moveProgress && <MoveJobProgress progress={moveProgress} />}
      {moveConfirmation}
      {/* F034: Move files/folders (same-space + cross-space) */}
      <MoveToDialog
        open={moveDialogOpen}
        onOpenChange={setMoveDialogOpen}
        currentSpaceId={space.id}
        currentSpaceName={space.name}
        onConfirm={handleMoveConfirm}
      />
      {versionManagementEnabled && (
        <>
          <VersionManagementDialog
            open={versionMgmtFile !== null}
            onOpenChange={(o) => {
              if (!o) setVersionMgmtFile(null);
            }}
            spaceId={spaceIdNum}
            file={versionMgmtFile}
            onLinked={() => {
              handleVersionAction();
              setVersionMgmtFile(null);
            }}
          />
          <VersionHistorySheet
            open={versionHistoryFile !== null}
            onOpenChange={(o) => {
              if (!o) setVersionHistoryFile(null);
            }}
            spaceId={spaceIdNum}
            fileId={versionHistoryFile ? Number(versionHistoryFile.id) : null}
            documentTitle={versionHistoryFile?.name}
            canManage={canEditSpace}
            onPreview={(versionFileId, fileName) =>
              handlePreviewFile(String(versionFileId), fileName)
            }
            onDownload={async (versionFileId, fileName, signal) => {
              try {
                const { original_url: downloadUrl } = await getFileDownloadApi(
                  String(space.id),
                  String(versionFileId),
                  signal,
                );
                if (signal.aborted) return;
                if (!downloadUrl) {
                  showToast({
                    message: localize("knowledge.version.history.download_feedback.no_url", { ns: "shared" }),
                    status: "warning",
                  });
                  return;
                }
                triggerUrlDownload(downloadUrl, fileName);
              } catch {
                if (signal.aborted) return;
                showToast({
                  message: localize("knowledge.version.history.download_feedback.failed", { ns: "shared" }),
                  status: "warning",
                });
              }
            }}
            onChanged={handleVersionAction}
          />
          <SimilarDocumentDialog
            open={similarDialogOpen}
            onOpenChange={(o) => {
              setSimilarDialogOpen(o);
              if (!o) setSimilarRestrictIds([]);
            }}
            spaceId={spaceIdNum}
            restrictToFileIds={similarRestrictIds}
            onProcessed={handleVersionAction}
          />
        </>
      )}
    </>
  );
}
