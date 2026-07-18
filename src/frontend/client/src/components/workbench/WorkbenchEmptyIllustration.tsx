import { NoPermissionIllustration } from '~/components/illustrations';

/**
 * Illustration for the menu-unavailable (no-permission) workstation placeholder.
 * Uses the brand-themed NoPermissionIllustration so it follows the blue ⇄ green
 * theme switch (was the legacy static channel/empty.png).
 */
export function WorkbenchEmptyIllustration() {
  return <NoPermissionIllustration className="h-[120px] w-[120px]" />;
}
