import { InlineCitation as SharedCitation,type InlineCitationProps } from '@bisheng/chat/citation-inline';
import { CitationSourceIcon } from './CitationSourceIcon';
import { useClientCitationServices } from './useClientCitationServices';
export function InlineCitation(props:InlineCitationProps){const services=useClientCitationServices();return <SharedCitation key={services.scopeKey+props.data.ref} {...props} presentation={{localize:services.localize,SourceIcon:CitationSourceIcon}}/>;}
