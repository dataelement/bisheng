import { StateView } from "@bisheng/ui";
import { EmptyStateIllustration } from "~/components/illustrations";

interface PermissionEmptyStateProps {
  /** Already-localized message. */
  message: string;
}

/**
 * Shared empty state for every permission list — the authorization panel, the
 * member list, and the three subject pickers in the grant dialog.
 *
 * All five containers are the main body of an 80vh dialog or a 400px panel, so
 * they take the page tier (120px art) of 组件-State状态页.md §3; StateView owns
 * the sizing, spacing and text tokens from here on.
 */
export function PermissionEmptyState({ message }: PermissionEmptyStateProps) {
  return <StateView image={<EmptyStateIllustration />} title={message} />;
}
