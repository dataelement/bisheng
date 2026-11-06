import { useContext,useMemo } from 'react';
import { MarkdownServicesContext } from './MarkdownServices';
import { useCitationReferences, type CitationReadServices } from '../citations/useCitationReferences';
import type { ChatCitation,CitationDisplayData } from './types';
export function useCitationDetails(citations:ChatCitation[]|null|undefined,citationMap:Record<string,CitationDisplayData>,hostServices?:CitationReadServices,allowRemoteResolve=true){
 const context=useContext(MarkdownServicesContext);const services=hostServices??(context?{...context,scopeKey:context.scopeKey??''}:null);
 if(!services)throw new Error('Citation read services are missing');
 const referenceItems=useMemo(()=>Object.values(citationMap).map(data=>({key:data.ref,data})),[citationMap]);
 const state=useCitationReferences({content:'',citations,referenceItems,services,allowRemoteResolve});
 const forbidden=new Set<string>();const expired=new Set<string>();
 for(const item of state.references){const id=item.data.citationId;const reason=services.getCitationUnresolvedReason(id);if(reason==='expired')expired.add(id);else if(reason==='forbidden'||(state.status==='ready'&&state.errorMap[id]))forbidden.add(id);}
 return {details:state.detailMap,forbidden,expired,load:state.loadCitationDetail};
}
