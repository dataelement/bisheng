import { CitationReferences } from '@bisheng/chat/citation-views';
import type { ChatCitation } from '@bisheng/chat/citations';
import { notification } from '@bisheng/ui';
import { usePlatformCitationServices } from './usePlatformCitationServices';
import { renderPlatformCitationFile } from './PlatformCitationFile';
import { useCitationMediaQuery } from './useCitationMediaQuery';
interface PlatformReferencesProps {content:string;webContent?:unknown;citations?:ChatCitation[]|null;buttonClassName?:string;allowRemoteCitationResolve?:boolean}
export function PlatformCitationReferencesDrawer({allowRemoteCitationResolve=false,...props}:PlatformReferencesProps){
 const services=usePlatformCitationServices();const isNarrowLayout=useCitationMediaQuery('(max-width:768px)');
 return <CitationReferences {...props} services={services} renderFile={renderPlatformCitationFile} isNarrowLayout={isNarrowLayout} allowRemoteResolve={allowRemoteCitationResolve} onUnavailable={message=>notification.open({type:'warning',title:message,description:''})}/>;
}
export { PlatformCitationReferencesDrawer as default };
