import { getCitationAccessScope } from '@/controllers/citationScope';
import { ChatMarkdown, type ChatMarkdownProps, type ChatCitation } from '@bisheng/chat';
import { useTranslation } from 'react-i18next';
import { getCitationDetail, getCitationUnresolvedReason, resolveCitationDetails, type ChatCitation as PlatformCitation } from '@/controllers/API';
import CitationDocumentPreviewDrawer from '../chatComponent/CitationDocumentPreviewDrawer';
import { CitationSourceIcon } from '../chatComponent/CitationSourceIcon';
import { loadScript } from '@/workspace/markdown/Mermaid';
import { copyText } from '@/utils';
function platformCitation(detail: ChatCitation): PlatformCitation { return { ...detail, itemId: detail.itemId ?? undefined }; }
/** Platform supplies authenticated resource reads and its existing preview host. */
export function PlatformChatMarkdown(props: Omit<ChatMarkdownProps, 'services'>) {
    const { t } = useTranslation(['bs', 'shared']);
    return <ChatMarkdown {...props} services={{ scopeKey:getCitationAccessScope(),localize: (key, options) => String(t(key, options)),
        getCitationDetail: async id => { const detail = await getCitationDetail(id); return { ...detail, type: detail.type ?? '' }; },
        resolveCitationDetails: async ids => (await resolveCitationDetails(ids)).map(detail => ({ ...detail, type: detail.type ?? '' })),
        getCitationUnresolvedReason,
        SourceIcon: values => <CitationSourceIcon {...values} detail={values.detail ? platformCitation(values.detail) : null} />,
        copyText, loadDiagramLibrary: loadScript,
        renderDocumentPreview: (preview, onClose) => <CitationDocumentPreviewDrawer preview={preview ? { ...preview, detail: platformCitation(preview.detail) } : null} onClose={onClose} />,
    }} />;
}
