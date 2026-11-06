import { CitationDocumentPreviewDrawer as SharedDrawer, CitationDocumentPreview, type CitationFileProps } from '@bisheng/chat/citation-views';
import type { CitationDocumentPreviewState } from '@bisheng/chat/citations';
import { useSetRecoilState } from 'recoil';
import store from '~/store';
import FilePreview from '~/pages/knowledge/FilePreview';
import { usePrefersMobileLayout } from '~/hooks';
import { useClientCitationServices } from './useClientCitationServices';
export type { CitationDocumentPreviewState } from '@bisheng/chat/citations';
export function renderClientCitationFile(props:CitationFileProps){return <FilePreview {...props}/>;}
interface ContentProps {preview:CitationDocumentPreviewState|null;compactMode?:boolean;className?:string}
export function CitationDocumentPreviewContent(props:ContentProps){
 const services=useClientCitationServices();
 return <CitationDocumentPreview {...props} services={services} renderFile={renderClientCitationFile}/>;
}
interface DrawerProps {preview:CitationDocumentPreviewState|null;onClose:()=>void;manageMobileNavVisibility?:boolean}
export function ClientCitationDocumentPreviewDrawer(props:DrawerProps){
 const services=useClientCitationServices();const isNarrowLayout=usePrefersMobileLayout();
 const hideNav=useSetRecoilState(store.chatMobileNavHiddenState);
 return <SharedDrawer {...props} services={services} renderFile={renderClientCitationFile} isNarrowLayout={isNarrowLayout} onMobileNavVisibility={hideNav}/>;
}
export { ClientCitationDocumentPreviewDrawer as default };
