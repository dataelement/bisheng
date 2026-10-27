import { createContext, useContext, useMemo, useRef } from 'react';
import { createCitationUtilities } from './citationPreview';
import type { MarkdownServices } from './types';
export const MarkdownServicesContext = createContext<MarkdownServices | null>(null);
export function useMarkdownServices(): MarkdownServices {
  const services = useContext(MarkdownServicesContext);
  if (!services) throw new Error('Markdown services are missing');
  return services;
}
export type CitationPresentation = Pick<MarkdownServices,'localize'|'SourceIcon'>;
export const CitationPresentationContext=createContext<CitationPresentation|null>(null);
export function useCitationPresentation():CitationPresentation {
  const presentation=useContext(CitationPresentationContext);const markdown=useContext(MarkdownServicesContext);
  const value=presentation??markdown;if(!value)throw new Error('Citation presentation is missing');return value;
}
export function useCitationUtilities() {
  const { localize } = useCitationPresentation();
  const latest=useRef(localize);latest.current=localize;
  return useMemo(() => createCitationUtilities((key,options)=>latest.current(key,options)), []);
}
