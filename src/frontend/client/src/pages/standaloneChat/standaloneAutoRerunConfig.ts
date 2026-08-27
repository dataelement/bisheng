import type { BishengConfig } from '~/@types/chat';

type StandaloneFlowType = 'workflow' | 'assistant';

export async function loadStandaloneAutoRerunOnOpen(
  flowType: StandaloneFlowType,
  loadConfig: () => Promise<unknown>,
): Promise<boolean> {
  if (flowType !== 'workflow') return false;

  try {
    const response = await loadConfig();
    const config = (response as { data?: BishengConfig } | null)?.data;
    const configuredValue = config?.workflow?.auto_rerun_on_open;
    return typeof configuredValue === 'boolean' ? configuredValue : false;
  } catch {
    return false;
  }
}
