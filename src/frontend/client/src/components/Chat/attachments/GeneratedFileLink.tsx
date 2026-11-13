import type { ReactNode } from 'react';
import type { ArtifactFile } from '~/components/Linsight/Artifacts/artifactUtils';
import { downloadFile } from '~/utils';
import {
    getChatAttachmentFileName,
    getReissuableAttachment,
    reissueAttachmentUrl,
    resolveChatAttachmentUrl,
} from './chatAttachmentUtils';
import { toChatArtifact } from './collectChatAttachments';

export interface GeneratedFile {
    file_id?: string;
    file_name?: string;
    path?: string;
    object_name?: string;
    filepath?: string;
}

function normalizeHref(href: string): string {
    let decoded = href;
    try {
        decoded = decodeURIComponent(href);
    } catch {
        // A stray `%` in a model-written link; match it as written.
    }
    return decoded.replace(/\\/g, '/').replace(/^\.\//, '').replace(/^\/+/, '');
}

/** A relative link into the code interpreter's working directory, which is no route of this app. */
export function isWorkspaceRelativeHref(href: string): boolean {
    return /^(output|scratch)\//.test(normalizeHref(href));
}

/** The generated file an answer's link names, matched on its path in the working directory. */
export function matchGeneratedFile<T extends GeneratedFile>(files: T[], href: string): T | undefined {
    if (!href || !files.length || /^[a-z][a-z0-9+.-]*:/i.test(href)) return undefined;
    const target = normalizeHref(href);
    return files.find((file) => file.path && normalizeHref(file.path) === target);
}

interface GeneratedFileLinkProps {
    file: GeneratedFile;
    conversationId?: string;
    onPreviewFile?: (file: ArtifactFile) => void;
    children: ReactNode;
}

/** Opens a generated file named in the answer the same way its card does. */
export function GeneratedFileLink({ file, conversationId, onPreviewFile, children }: GeneratedFileLinkProps) {
    const handleClick = async () => {
        const artifact = toChatArtifact(file, conversationId);
        if (artifact && onPreviewFile) {
            onPreviewFile(artifact);
            return;
        }
        const url = await reissueAttachmentUrl(
            getReissuableAttachment(file, conversationId),
            resolveChatAttachmentUrl(file),
        );
        if (url) downloadFile(url, getChatAttachmentFileName(file));
    };

    return (
        <button
            type="button"
            className="text-blue-600 underline transition-colors hover:text-blue-700"
            onClick={handleClick}
        >
            {children}
        </button>
    );
}

/**
 * Link renderer for a daily-chat answer: a link naming a generated file opens
 * it; a working-directory link naming nothing becomes plain text; any other
 * link is left to the default renderer (undefined).
 */
export function renderGeneratedFileLink(
    files: GeneratedFile[],
    href: string,
    children: ReactNode,
    options: { conversationId?: string; onPreviewFile?: (file: ArtifactFile) => void },
): ReactNode | undefined {
    const matched = matchGeneratedFile(files, href);
    if (matched) {
        return (
            <GeneratedFileLink file={matched} conversationId={options.conversationId} onPreviewFile={options.onPreviewFile}>
                {children}
            </GeneratedFileLink>
        );
    }
    if (href && isWorkspaceRelativeHref(href)) return <span>{children}</span>;
    return undefined;
}
