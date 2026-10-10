/** Knowledge-page entry: UI, deployment and tenant gates must all be on. */
export function shouldShowPersonalTokenEntry(
  deploymentEnabled: boolean,
  effectiveEnabled: boolean | undefined,
  uiEnabled: boolean = false,
): boolean {
  return uiEnabled && deploymentEnabled && effectiveEnabled === true;
}

/**
 * Settings section: UI and deployment gates — while the tenant switch is off the
 * section stays and explains the pause instead of vanishing (AC-P30).
 */
export function shouldShowAiAccessSection(deploymentEnabled: boolean, uiEnabled: boolean = false): boolean {
  return uiEnabled && deploymentEnabled;
}
