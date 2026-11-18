import { useTranslation } from "react-i18next";
import type { SpaceCopyTask } from "@/controllers/API/knowledgeCopy";
import type { KnowledgeQueryScope } from "@/controllers/hooks/knowledge";
import { SpaceProcessingProgress } from "./SpaceProcessingProgress";

interface SpaceCopyStatusProps {
  scope: KnowledgeQueryScope;
  task: SpaceCopyTask;
  onCompleted: () => void;
}

export function SpaceCopyStatus({ scope, task, onCompleted }: SpaceCopyStatusProps) {
  const { t } = useTranslation("knowledge");
  return <section className="space-y-4 p-4" aria-live="polite">
    <h1 className="text-h4 text-text-1">{task.name}</h1>
    <p role="status">{t(`space_copy_ui.phase_${task.phase}`, {
      completed: task.succeeded_count, total: task.total_count,
    })}</p>
    <p className="text-body-sm text-text-3">{t("space_copy_ui.background_notice")}</p>
    {(task.phase === "copying" || task.phase === "failed") && <SpaceProcessingProgress scope={scope} spaceId={task.id} jobId={task.job_id} kind="space_copy" onCompleted={onCompleted} />}
  </section>;
}
