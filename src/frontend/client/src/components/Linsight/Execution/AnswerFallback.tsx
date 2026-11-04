import { useMemo } from 'react';
import Markdown from '~/components/Chat/Messages/Content/Markdown';
import { stripCitationMarkers } from '~/components/Chat/Messages/Content/citationUtils';
import { stripWorkspacePaths } from '~/components/Linsight/Artifacts/artifactUtils';
import '~/markdown.css';

/**
 * The persisted answer a task turn shows until its execution detail loads (or
 * when the load fails). The stored text is markdown carrying private-use
 * citation markers; the citation list only arrives with the detail, so the
 * markers are stripped here and the badges appear once ResultSection takes over.
 */
export function AnswerFallback({ answer }: { answer: string }) {
    const content = useMemo(() => stripCitationMarkers(stripWorkspacePaths(answer)), [answer]);
    return (
        <div className="bs-mkdown text-sm leading-6 text-gray-800 [&_p:last-child]:mb-0">
            <Markdown content={content} isLatestMessage={true} webContent={false} />
        </div>
    );
}
