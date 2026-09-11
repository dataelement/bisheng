import { EmptyStateIllustration } from "~/components/illustrations";
import { useLocalize } from "~/hooks";

interface PermissionEmptyStateProps {
  /** Already-localized message. */
  message: string;
}

/**
 * Shared empty state for every permission list — the authorization panel, the
 * member list, and the three subject pickers in the grant dialog. Illustration
 * above the message, centered in whatever height the parent gives it.
 */
export function PermissionEmptyState({ message }: PermissionEmptyStateProps) {
  const localize = useLocalize();

  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 py-10">
      <EmptyStateIllustration
        role="img"
        aria-label={localize("com_subscription.no_data")}
        className="size-[120px]"
      />
      <p className="text-body text-text-3">{message}</p>
    </div>
  );
}
