import { Button } from "@bisheng/ui";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  useKnowledgeProcessingJobs,
  type KnowledgeQueryScope,
} from "@/controllers/hooks/knowledge";
import { SpaceTaskRecordsDialog } from "./SpaceTaskRecordsDialog";

interface SpaceTaskRecordsButtonProps {
  scope: KnowledgeQueryScope;
  spaceId: number;
  canReadProcessing: boolean;
}

export function SpaceTaskRecordsButton({
  scope,
  spaceId,
  canReadProcessing,
}: SpaceTaskRecordsButtonProps) {
  const { t } = useTranslation("knowledge");
  const [open, setOpen] = useState(false);
  const processing = useKnowledgeProcessingJobs(
    scope,
    spaceId,
    { page: 1, page_size: 1, kind: "embedding_rebuild" },
    undefined,
    { enabled: canReadProcessing },
  );
  const moves = useKnowledgeProcessingJobs(scope, spaceId, {
    page: 1,
    page_size: 1,
    kind: "move_index",
  });
  const hasProcessing = canReadProcessing && (processing.data?.total ?? 0) > 0;
  const hasMoves = (moves.data?.total ?? 0) > 0;
  if (!hasProcessing && !hasMoves) return null;

  return (
    <SpaceTaskRecordsDialog
      scope={scope}
      spaceId={spaceId}
      open={open}
      onOpenChange={setOpen}
      canReadProcessing={canReadProcessing}
      initialKind={hasProcessing ? "embedding_rebuild" : "move_index"}
      trigger={
        <Button type="button" variant="outlined" color="default" className="shrink-0">
          {t("detail.task_records")}
        </Button>
      }
    />
  );
}
