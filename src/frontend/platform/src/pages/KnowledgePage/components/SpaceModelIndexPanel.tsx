import type { KnowledgeQueryScope } from "@/controllers/hooks/knowledge";
import { SpaceProcessingPanel } from "./SpaceProcessingDialog";
interface SpaceModelIndexPanelProps {
  scope: KnowledgeQueryScope;
  spaceId: number;
  onSaved: () => void;
}
export function SpaceModelIndexPanel(props: SpaceModelIndexPanelProps) {
  return (
    <div className="space-y-6">
      <SpaceProcessingPanel {...props} mode="embedding" />
      <div className="border-t border-border-base">
        <SpaceProcessingPanel
          scope={props.scope}
          spaceId={props.spaceId}
          mode="jobs"
          jobKind="embedding_rebuild"
        />
      </div>
    </div>
  );
}
