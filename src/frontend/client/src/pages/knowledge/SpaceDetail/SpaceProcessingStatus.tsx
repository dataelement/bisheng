import { useLocalize } from "~/hooks";

interface SpaceProcessingStatusProps {
  state?: number | null;
}

export function SpaceProcessingStatus({ state }: SpaceProcessingStatusProps) {
  const localize = useLocalize();
  if (state !== 3 && state !== 4) return null;
  return (
    <p
      role="status"
      className={`shrink-0 px-4 py-2 text-body-sm ${state === 4 ? "text-danger" : "text-text-2"}`}
    >
      {localize(`com_knowledge.processing_jobs.${state === 3 ? "rebuilding" : "rebuild_failed"}`)}
    </p>
  );
}
