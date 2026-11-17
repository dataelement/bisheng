import { useRef } from 'react';
import Markdown from '~/components/Chat/Messages/Content/Markdown';
import { LoadingIcon } from '~/components/ui/icon/Loading';
import { MarkdownOutline } from './MarkdownOutline';
import { usePreviewLayout } from './usePreviewLayout';

interface ArtifactMarkdownPreviewProps {
    content: string;
    resolveImageSrc: (src: string) => Promise<string | null>;
    resolveArtifactLink?: (href: string) => unknown;
    onArtifactPreview?: (file: unknown) => void;
}

export function ArtifactMarkdownPreview(props: ArtifactMarkdownPreviewProps) {
    const rootRef = useRef<HTMLDivElement>(null);
    const contentRef = useRef<HTMLDivElement>(null);
    const revision = usePreviewLayout(rootRef);

    return (
        <div ref={rootRef} className="group/mk relative min-h-full">
            <MarkdownOutline contentRef={contentRef} contentKey={props.content} />
            <div ref={contentRef} className="bs-mkdown p-8">
                {revision === 0 ? (
                    <div className="flex justify-center py-8">
                        <LoadingIcon className="size-20 text-primary" />
                    </div>
                ) : (
                    <Markdown
                        key={revision}
                        {...props}
                        isLatestMessage={false}
                        webContent={false}
                    />
                )}
            </div>
        </div>
    );
}
