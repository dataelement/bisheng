import { Segmented } from "@bisheng/ui";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/bs-ui/dialog";
import {
  knowledgeQueryKeys,
  type KnowledgeQueryScope,
} from "@/controllers/hooks/knowledge";
import { SpaceProcessingPanel } from "./SpaceProcessingDialog";

interface SpaceTaskRecordsDialogProps {
  scope: KnowledgeQueryScope;
  spaceId: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  canReadProcessing: boolean;
  initialKind?: "embedding_rebuild" | "move_index";
}

export function SpaceTaskRecordsDialog({
  scope,
  spaceId,
  open,
  onOpenChange,
  canReadProcessing,
  initialKind = "embedding_rebuild",
}: SpaceTaskRecordsDialogProps) {
  const { t } = useTranslation("knowledge");
  const title = t("detail.task_records");

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="flex h-[min(clamp(24rem,80dvh,48rem),calc(100dvh-3rem))] w-[calc(100vw-32px)] max-w-[600px] flex-col overflow-hidden"
        aria-describedby={undefined}
      >
        <DialogHeader className="shrink-0 text-left">
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        <div className="flex min-h-0 flex-1 flex-col">
          <TaskRecordsContent
            scope={scope}
            spaceId={spaceId}
            canReadProcessing={canReadProcessing}
            initialKind={initialKind}
          />
        </div>
      </DialogContent>
    </Dialog>
  );
}

function TaskRecordsContent({
  scope,
  spaceId,
  canReadProcessing,
  initialKind,
}: Pick<SpaceTaskRecordsDialogProps, "scope" | "spaceId" | "canReadProcessing" | "initialKind">) {
  const { t } = useTranslation("knowledge");
  const client = useQueryClient();
  const [selectedKind, setSelectedKind] = useState(initialKind ?? "embedding_rebuild");
  const kind = canReadProcessing ? selectedKind : "move_index";

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      {canReadProcessing && (
        <Segmented
          className="shrink-0 self-start"
          aria-label={t("detail.task_records")}
          value={kind}
          onChange={(value) => setSelectedKind(value as "embedding_rebuild" | "move_index")}
          options={[
            {
              value: "embedding_rebuild",
              label: t("f118.processing_title_jobs"),
            },
            {
              value: "move_index",
              label: t("move.jobs"),
            },
          ]}
        />
      )}
      <SpaceProcessingPanel
        scope={scope}
        spaceId={spaceId}
        mode="jobs"
        jobKind={kind}
        presentation="inline"
        fill
        hideTitle={canReadProcessing}
        onSaved={kind === "move_index" ? () => {
          void client.invalidateQueries({ queryKey: knowledgeQueryKeys.scope(scope) });
        } : undefined}
      />
    </div>
  );
}
