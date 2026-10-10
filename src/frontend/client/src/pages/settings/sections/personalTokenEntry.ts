/** Knowledge-page entry: both gates must be on (tenant off hides it). */
export function shouldShowPersonalTokenEntry(
  deploymentEnabled: boolean,
  effectiveEnabled: boolean | undefined,
): boolean {
  return deploymentEnabled && effectiveEnabled === true;
}

/**
 * Settings section: deployment gate only — while the tenant switch is off the
 * section stays and explains the pause instead of vanishing (AC-P30).
 */
export function shouldShowAiAccessSection(deploymentEnabled: boolean): boolean {
  return deploymentEnabled;
}
