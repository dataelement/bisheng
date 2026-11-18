import type { KnowledgeQueryScope } from "@/controllers/hooks/knowledge";
import type {
  ProcessingKind,
  ProcessingTargetInput,
} from "@/controllers/API/knowledgeSpace";

export interface SpaceProcessingDialogProps {
  scope: KnowledgeQueryScope;
  spaceId: number;
  mode: "embedding" | "file" | "jobs";
  target?: ProcessingTargetInput;
  fileId?: number;
  includeCopies?: boolean;
  jobKind?: ProcessingKind;
  hideTitle?: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved?: () => void;
  onBack?: () => void;
  presentation?: "page" | "inline";
}
