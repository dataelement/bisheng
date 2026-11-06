import { CitationDocumentPreviewDrawer as SharedDrawer, CitationDocumentPreview } from '@bisheng/chat/citation-views';
import type { CitationDocumentPreviewState } from '@bisheng/chat/citations';
import { usePlatformCitationServices } from './usePlatformCitationServices';
import { renderPlatformCitationFile } from './PlatformCitationFile';
import { useCitationMediaQuery } from './useCitationMediaQuery';
export type { CitationDocumentPreviewState } from '@bisheng/chat/citations';
interface ContentProps {preview:CitationDocumentPreviewState|null;compactMode?:boolean;className?:string}
export function CitationDocumentPreviewContent(props:ContentProps){
 const services=usePlatformCitationServices();return <CitationDocumentPreview {...props} services={services} renderFile={renderPlatformCitationFile}/>;
}
interface DrawerProps {preview:CitationDocumentPreviewState|null;onClose:()=>void}
export function PlatformCitationDocumentPreviewDrawer(props:DrawerProps){
 const services=usePlatformCitationServices();const isNarrowLayout=useCitationMediaQuery('(max-width:768px)');
 return <SharedDrawer {...props} services={services} renderFile={renderPlatformCitationFile} isNarrowLayout={isNarrowLayout} showDesktopDownload/>;
}
export { PlatformCitationDocumentPreviewDrawer as default };
