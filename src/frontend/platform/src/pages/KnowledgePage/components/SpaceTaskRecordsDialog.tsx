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

import { SpaceProviderOperations } from './SpaceProviderOperations';

type TaskKind = 'embedding_rebuild' | 'move_index' | 'provider_operations';

interface SpaceTaskRecordsDialogProps {
  scope: KnowledgeQueryScope;
  spaceId: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  canReadProcessing: boolean;
  canReadProviderOperations: boolean;
  initialKind?: TaskKind;
}

export function SpaceTaskRecordsDialog({
  scope,
  spaceId,
  open,
  onOpenChange,
  canReadProcessing,
  canReadProviderOperations,
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
          {open && <TaskRecordsContent
            scope={scope}
            spaceId={spaceId}
            canReadProcessing={canReadProcessing}
            canReadProviderOperations={canReadProviderOperations}
            initialKind={initialKind}
          />}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function TaskRecordsContent({
  scope,
  spaceId,
  canReadProcessing,
  canReadProviderOperations,
  initialKind,
}: Pick<SpaceTaskRecordsDialogProps, "scope" | "spaceId" | "canReadProcessing" | "canReadProviderOperations" | "initialKind">) {
  const { t } = useTranslation("knowledge");
  const client = useQueryClient();
  const [selectedKind, setSelectedKind] = useState(initialKind ?? "embedding_rebuild");
  const kind = (selectedKind === "provider_operations" && !canReadProviderOperations) ||
    (selectedKind === "embedding_rebuild" && !canReadProcessing) ? "move_index" : selectedKind;
  const showKinds = canReadProcessing || canReadProviderOperations;

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      {showKinds && (
        <Segmented
          className="shrink-0 self-start"
          aria-label={t("detail.task_records")}
          value={kind}
          onChange={(value) => setSelectedKind(value as TaskKind)}
          options={[
            ...(canReadProcessing ? [{ value: "embedding_rebuild", label: t("f118.processing_title_jobs") }] : []),
            {
              value: "move_index",
              label: t("move.jobs"),
            },
            ...(canReadProviderOperations ? [{ value: "provider_operations", label: t("provider_operations.title") }] : []),
          ]}
        />
      )}
      {kind === "provider_operations" ? <SpaceProviderOperations scope={scope} spaceId={spaceId} /> : <SpaceProcessingPanel
        scope={scope}
        spaceId={spaceId}
        mode="jobs"
        jobKind={kind}
        presentation="inline"
        fill
        hideTitle={showKinds}
        onSaved={kind === "move_index" ? () => {
          void client.invalidateQueries({ queryKey: knowledgeQueryKeys.scope(scope) });
        } : undefined}
      />}
    </div>
  );
}
