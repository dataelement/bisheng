import { KnowledgeDialogTable } from "@bisheng/knowledge";
import { useTranslation } from "react-i18next";
import type { ProcessingJobRead } from "@/controllers/API/knowledgeSpace";
import { processingFailureKey } from "./processingFailure";
import { SpaceProcessingStatus } from "./SpaceProcessingStatus";

interface SpaceProcessingJobsTableProps {
  title: string;
  jobs: readonly ProcessingJobRead[];
  onSelect: (job: ProcessingJobRead) => void;
  scrollable?: boolean;
}

export function SpaceProcessingJobsTable({ title, jobs, onSelect, scrollable }: SpaceProcessingJobsTableProps) {
  const { t } = useTranslation("knowledge");
  return (
    <KnowledgeDialogTable
      caption={title}
      showCaption={false}
      scrollable={scrollable}
      columns={[{ label: t("type") }, { label: t("status") }]}
      rows={jobs.map((job) => {
        const label = t(job.kind === "move_index" ? "move.jobs" : `f118.processing_kind_${job.kind}`);
        const status = t(job.state === "obsolete" ? "f118.processing_item_obsolete" : `f118.processing_state_${job.state}`);
        const reasonKey = processingFailureKey(job, job.kind)
          ?? (job.state === "obsolete" ? "f118.processing_state_obsolete" : undefined);
        return {
          key: job.id,
          cells: [
            <span
              role="link"
              tabIndex={0}
              className="cursor-pointer text-blue-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
              aria-label={`${label} · ${status}`}
              onClick={() => onSelect(job)}
              onKeyDown={(event) => {
                if (event.key === "Enter") onSelect(job);
              }}
            >
              {label}
            </span>,
            <SpaceProcessingStatus state={job.state} label={status} reasonKey={reasonKey} />,
          ],
        };
      })}
    />
  );
}
