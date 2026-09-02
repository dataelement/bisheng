import type { WorkbenchModelOption } from './Chat/ModelAvailabilityOption';

interface RecoveryChatModelSelection {
  id: number;
  name: string;
  manual?: boolean;
  mode?: 'daily' | 'task';
}

export function buildRecoveryChatModelSelection(
  current: RecoveryChatModelSelection,
  modelId: string,
  modelName: string,
): RecoveryChatModelSelection {
  return {
    ...current,
    id: Number(modelId),
    name: modelName,
    manual: true,
  };
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
