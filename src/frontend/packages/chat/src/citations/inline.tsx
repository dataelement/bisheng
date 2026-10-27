import type { ComponentProps } from 'react';
import { Citation } from '../content/Citation';
import { CitationPresentationContext, type CitationPresentation } from '../content/MarkdownServices';
export { useCitationDetails } from '../content/useCitationDetails';
export type InlineCitationProps=ComponentProps<typeof Citation>;
export function InlineCitation({presentation,...props}:InlineCitationProps&{presentation:CitationPresentation}){
 return <CitationPresentationContext.Provider value={presentation}><Citation {...props}/></CitationPresentationContext.Provider>;
}
