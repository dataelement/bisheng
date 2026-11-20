import { Button, Tag, Tooltip, type TagColor } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { useTranslation } from "react-i18next";
import type { ItemState, JobState } from "@/controllers/API/knowledgeSpace";

const STATUS_COLORS: Record<JobState | ItemState, TagColor> = {
  accepted: "default",
  pending: "default",
  running: "brand",
  succeeded: "success",
  partial_failed: "warning",
  failed: "danger",
  obsolete: "danger",
};

interface SpaceProcessingStatusProps {
  state: JobState | ItemState;
  label: string;
  reasonKey?: string;
}

export function SpaceProcessingStatus({ state, label, reasonKey }: SpaceProcessingStatusProps) {
  const { t } = useTranslation("knowledge");
  const reason = reasonKey ? t(reasonKey) : undefined;
  return (
    <span className="inline-flex items-center gap-1 whitespace-nowrap">
      <Tag size="small" dot color={STATUS_COLORS[state]}>{label}</Tag>
      {reason && (
        <Tooltip content={reason}>
          <Button
            type="button"
            variant="text"
            color="default"
            size="small"
            iconOnly
            aria-label={reason}
            className="text-text-3"
          >
            <Outlined.Question aria-hidden />
          </Button>
        </Tooltip>
      )}
    </span>
  );
}
