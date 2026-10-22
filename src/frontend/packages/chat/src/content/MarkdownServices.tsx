import { createContext, useContext, useMemo } from 'react';
import { createCitationUtilities } from './citationPreview';
import type { MarkdownServices } from './types';
export const MarkdownServicesContext = createContext<MarkdownServices | null>(null);
export function useMarkdownServices(): MarkdownServices {
  const services = useContext(MarkdownServicesContext);
  if (!services) throw new Error('Markdown services are missing');
  return services;
}
export function useCitationUtilities() {
  const { localize } = useMarkdownServices();
  return useMemo(() => createCitationUtilities(localize), [localize]);
}
