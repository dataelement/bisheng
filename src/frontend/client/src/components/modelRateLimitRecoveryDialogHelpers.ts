import type { WorkbenchModelOption } from './Chat/ModelAvailabilityOption';

export function isRecoveryConfirmationAccepted(result: unknown): boolean {
  if (result === false) return false;
  if (typeof result !== 'object' || result === null || !('accepted' in result)) return true;
  return (result as { accepted?: unknown }).accepted !== false;
}

export function getRecoveryModelCandidates(
  models: WorkbenchModelOption[],
  currentModelId: string | number,
  isCompatible: (model: WorkbenchModelOption) => boolean = () => true,
): WorkbenchModelOption[] {
  const currentId = String(currentModelId);
  const seen = new Set<string>();

  return models.filter((model) => {
    const id = String(model.id);
    const busy = model.rateLimitState === 'busy' || model.rateLimitState === 'recovering';
    if (
      !id
      || id === currentId
      || seen.has(id)
      || busy
      || !isCompatible(model)
    ) {
      return false;
    }
    seen.add(id);
    return true;
  });
}
