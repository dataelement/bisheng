import { createPortal } from "react-dom";
import { WorkspacePanel } from "~/components/Linsight/Artifacts/WorkspacePanel";
import type { ChatViewModel } from "./ChatView";
interface TaskWorkspacePresentationProps {
  model: ChatViewModel;
}
export function TaskWorkspacePresentation({
  model,
}: TaskWorkspacePresentationProps) {
  const {
    isCompactLayout,
    latestTaskVersionId,
    taskArtifacts,
    chatAttachments,
    fsMounted,
    setFsMounted,
    fsExpanded,
    fsBox,
    taskLinsight,
    taskWorkspaceFiles,
    taskWorkspaceLoadState,
  } = model;
  return (
    <>
      {" "}
      {(latestTaskVersionId || chatAttachments.length > 0) &&
        !isCompactLayout &&
        fsMounted &&
        fsBox &&
        createPortal(
          <div
            className="dsh-chat-preview-modal fixed z-[100] overflow-hidden border border-border-base bg-bg-page transition-[top,left,right,bottom,padding,border-radius] duration-300 ease-[cubic-bezier(0.32,0.72,0,1)]"
            style={{
              ...(fsExpanded ? fsBox.expanded : fsBox.collapsed),
              padding: fsExpanded ? 4 : 0,
              borderRadius: fsExpanded ? 12 : 8,
            }}
            onTransitionEnd={(e) => {
              // Unmount only after the collapse finishes (ignore the expand end
              // and bubbled child transitions).
              if (
                e.target === e.currentTarget &&
                e.propertyName === "left" &&
                !taskArtifacts.fullscreen
              ) {
                setFsMounted(false);
              }
            }}
          >
            <WorkspacePanel
              files={[...chatAttachments, ...taskWorkspaceFiles]}
              loading={taskWorkspaceLoadState === "loading"}
              loadFailed={taskWorkspaceLoadState === "failed"}
              versionId={latestTaskVersionId}
              citations={taskLinsight?.output_result?.citations}
              messageId={taskLinsight?.message_id ?? undefined}
              previewFile={taskArtifacts.previewFile}
              fullscreen={true}
              sourcePreview={taskArtifacts.sourcePreview}
              onOpenSource={taskArtifacts.openSource}
              onCloseSource={taskArtifacts.closeSource}
              onPreview={taskArtifacts.openPreview}
              onBack={taskArtifacts.backToList}
              onClose={taskArtifacts.closeWorkspace}
              onToggleFullscreen={taskArtifacts.toggleFullscreen}
            />
          </div>,
          document.body,
        )}
    </>
  );
}
