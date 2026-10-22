import { splitMessageContent } from '@bisheng/chat/core';
import { ChatMarkdown, type ChatMarkdownProps, type MarkdownCodeProps } from '@bisheng/chat';
import { useRef, type ComponentProps } from 'react';
import { getCitationDetail, getCitationUnresolvedReason, resolveCitationDetails } from '~/api/chatApi';
import { getFileDownload } from '~/api/chat/data-service';
import { ArtifactProvider, CodeBlockProvider, useCodeBlockContext, useToastContext } from '~/Providers';
import { Artifact } from '~/components/Artifacts/Artifact';
import RunCode from '~/components/Messages/Content/RunCode';
import CitationDocumentPreviewDrawer from '~/components/Chat/Messages/Content/CitationDocumentPreviewDrawer';
import { CitationSourceIcon } from '~/components/Chat/Messages/Content/CitationSourceIcon';
import { loadScript } from '~/components/Chat/Messages/Content/Mermaid';
import { useAuthContext, useLocalize } from '~/hooks';
import useHasAccess from '~/hooks/Roles/useHasAccess';
import { Permissions, PermissionTypes } from '~/types/chat';
import { copyText } from '~/utils';

function ClientCodeActions({ language, codeRef }: MarkdownCodeProps) {
    const { getNextIndex } = useCodeBlockContext();
    const index = useRef(getNextIndex(false)).current;
    return codeRef ? <RunCode lang={language} codeRef={codeRef} blockIndex={index} /> : null;
}
interface ClientChatMarkdownProps extends Omit<ChatMarkdownProps, 'services'> { readOnly: boolean; latexParsing?: boolean }
/** Only client permissions, previews and writes live here; Markdown belongs to chat. */
export function ClientChatMarkdown({ readOnly, latexParsing, ...props }: ClientChatMarkdownProps) {
    const localize = useLocalize();
    const parsed = splitMessageContent(props.content);
    const { user } = useAuthContext();
    const { showToast } = useToastContext();
    const canRunCode = useHasAccess({ permissionType: PermissionTypes.RUN_CODE, permission: Permissions.USE });
    return <ArtifactProvider><CodeBlockProvider><ChatMarkdown {...props} content={parsed.referenceText} webContent={props.webContent ?? parsed.webContent} services={{
        localize, latexParsing,
        getCitationDetail, resolveCitationDetails, getCitationUnresolvedReason, SourceIcon: CitationSourceIcon,
        copyText,
        renderDocumentPreview: (preview, onClose) => <CitationDocumentPreviewDrawer preview={preview} onClose={onClose} />,
        loadDiagramLibrary: loadScript,
        renderCodeActions: code => !readOnly && canRunCode ? <ClientCodeActions {...code} /> : null,
        renderArtifact: values => <Artifact {...values as unknown as ComponentProps<typeof Artifact>} />,
        onLinkClick: async (href, event) => {
            const match = href.match(new RegExp(`(?:files|outputs)/${user?.id}/([^\\s]+)`));
            if (!match) return;
            const parts = match[0].split('/'); const filename = parts.pop(); const id = parts.pop();
            if (!filename || !id || !user?.id) return;
            event.preventDefault();
            try {
                const response = await getFileDownload(user.id, id);
                if (!response.data) { showToast({ status: 'warning', message: localize('com_ui_download_error') }); return; }
                const url = URL.createObjectURL(response.data);
                const link = document.createElement('a'); link.href = url; link.download = filename;
                document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(url);
            } catch { /* The authenticated request interceptor reports download errors. */ }
        },
    }} /></CodeBlockProvider></ArtifactProvider>;
}
