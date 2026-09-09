export function shouldShowPersonalTokenEntry(
  deploymentEnabled: boolean,
  effectiveEnabled: boolean | undefined,
): boolean {
  return deploymentEnabled && effectiveEnabled === true;
}
