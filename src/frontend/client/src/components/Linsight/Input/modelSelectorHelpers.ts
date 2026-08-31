import type { WorkbenchModelOption } from '~/components/Chat/ModelAvailabilityOption';

export function getUniqueWorkbenchModels(
  models: WorkbenchModelOption[],
): WorkbenchModelOption[] {
  const seen = new Set<string>();
  return models.filter((option) => {
    if (option.id == null || String(option.id) === '') return false;
    const id = String(option.id);
    if (seen.has(id)) return false;
    seen.add(id);
    return true;
  });
}

export function getTaskDefaultModelId(
  options: WorkbenchModelOption[],
  administratorDefault?: string | number | null,
): string {
  if (options.length === 0) return '';
  if (
    administratorDefault != null
    && options.some((option) => String(option.id) === String(administratorDefault))
  ) {
    return String(administratorDefault);
  }
  return String(options[0].id);
}
