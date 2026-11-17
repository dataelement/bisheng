import { Tabs } from "@bisheng/ui";
import { useQueryClient } from "@tanstack/react-query";
import type { ReactElement } from "react";
import { useTranslation } from "react-i18next";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
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
  trigger?: ReactElement;
}

export function SpaceTaskRecordsDialog({
  scope,
  spaceId,
  open,
  onOpenChange,
  canReadProcessing,
  initialKind = "embedding_rebuild",
  trigger,
}: SpaceTaskRecordsDialogProps) {
  const { t } = useTranslation("knowledge");
  const client = useQueryClient();
  const title = t("detail.task_records");
  const moves = (
    <SpaceProcessingPanel
      scope={scope}
      spaceId={spaceId}
      mode="jobs"
      jobKind="move_index"
      presentation="inline"
      hideTitle={canReadProcessing}
      onSaved={() => {
        void client.invalidateQueries({ queryKey: knowledgeQueryKeys.scope(scope) });
      }}
    />
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {trigger && <DialogTrigger asChild>{trigger}</DialogTrigger>}
      <DialogContent
        className="flex max-h-[calc(100dvh-64px)] w-[calc(100vw-32px)] max-w-[600px] flex-col"
        aria-describedby={undefined}
      >
        <DialogHeader className="shrink-0 text-left">
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        <div className="min-h-0 overflow-y-auto overscroll-contain">
          {canReadProcessing ? (
            <Tabs
              aria-label={title}
              size="small"
              className="space-y-3"
              defaultActiveKey={initialKind}
              items={[
                {
                  key: "embedding_rebuild",
                  label: t("f118.processing_title_jobs"),
                  children: (
                    <SpaceProcessingPanel
                      scope={scope}
                      spaceId={spaceId}
                      mode="jobs"
                      jobKind="embedding_rebuild"
                      presentation="inline"
                      hideTitle
                    />
                  ),
                },
                { key: "move_index", label: t("move.jobs"), children: moves },
              ]}
            />
          ) : moves}
        </div>
      </DialogContent>
    </Dialog>
  );
}
