import { Button } from "~/components/ui/Button";
import { useLocalize } from "~/hooks";

export interface CreatedPermissionFailureStateProps {
  retryStatus: "idle" | "retrying" | "success" | "failed";
  onRetry: () => Promise<boolean>;
  onEnter: () => void;
}

export function CreatedPermissionFailureState({
  retryStatus,
  onRetry,
  onEnter,
}: CreatedPermissionFailureStateProps) {
  const localize = useLocalize();

  return (
    <main className="flex h-full min-h-0 items-center justify-center bg-fill-1 p-4">
      <section className="w-full max-w-[648px] rounded-xl bg-surface-primary p-8 text-center shadow-sm">
        <h1 className="text-h3 text-text-1">
          {localize(
            "com_unified_permission.resource_created_permission_failed",
          )}
        </h1>
        <div className="mt-6 flex flex-wrap justify-center gap-3">
          <Button
            onClick={async () => {
              if (await onRetry()) onEnter();
            }}
            disabled={retryStatus === "retrying" || retryStatus === "success"}
          >
            {localize("com_unified_permission.retry_permission")}
          </Button>
          <Button variant="secondary" onClick={onEnter}>
            {localize("com_unified_permission.enter_space")}
          </Button>
        </div>
      </section>
    </main>
  );
}
