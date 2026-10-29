import { CitationReferences, type CitationReferencesProps } from '@bisheng/chat/citation-views';
import { useSetRecoilState } from 'recoil';
import store from '~/store';
import { usePrefersMobileLayout } from '~/hooks';
import { useToastContext } from '~/Providers';
import { useClientCitationServices } from './useClientCitationServices';
import { renderClientCitationFile } from './CitationDocumentPreviewDrawer';
export type { CitationReferencesDesktopPayload } from '@bisheng/chat/citation-views';
interface ClientReferencesProps extends Omit<CitationReferencesProps,'services'|'renderFile'|'isNarrowLayout'|'onMobileNavVisibility'|'onUnavailable'> {
  /** Client callers can place existing message actions beside the source control. */
  actionButtons?: React.ReactNode;
}
export function ClientCitationReferencesDrawer(props:ClientReferencesProps){
 const services=useClientCitationServices();const isNarrowLayout=usePrefersMobileLayout();
 const hideNav=useSetRecoilState(store.chatMobileNavHiddenState);const {showToast}=useToastContext();
 return <CitationReferences {...props} services={services} renderFile={renderClientCitationFile} isNarrowLayout={isNarrowLayout} onMobileNavVisibility={hideNav} onUnavailable={message=>showToast({message,status:'warning'})}/>;
}
export { ClientCitationReferencesDrawer as default };
