import type { ComponentProps } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';
import { usePreviewResource } from '../usePreviewResource';
import type { PreviewViewerProps } from '../viewerTypes';
import { PreviewState, readPreview, usePreviewFailure } from './PreviewState';
// The existing highlight plugin uses VFile 5 types; its runtime remains compatible with Markdown's VFile 6.
const highlightPlugins = [[rehypeHighlight, { detect: true, ignoreMissing: true }]] as unknown as NonNullable<ComponentProps<typeof ReactMarkdown>['rehypePlugins']>;
export function MarkdownBody({ content, className = '' }: { content: string; className?: string }) {
  return <div className={`preview-prose prose prose-sm max-w-none break-words text-text-1 [&_pre]:max-w-full [&_pre]:overflow-x-auto [&_img]:h-auto [&_img]:max-w-full [&_table]:block [&_table]:max-w-full [&_table]:overflow-x-auto ${className}`}>
    <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={highlightPlugins}>{content}</ReactMarkdown>
  </div>;
}
export function MarkdownViewer({ resource, zoomLevel = 100, locale, onError }: PreviewViewerProps) {
  const url = resource.previewUrl || resource.originalUrl;
  const state = usePreviewResource(url, async signal => (await readPreview(url, signal)).text());
  usePreviewFailure(state.error, onError);
  if (state.status !== 'ready') return <PreviewState loading={state.status === 'loading'} locale={locale} />;
  return <div className="scrollbar-os flex-1 overflow-auto bg-fill-1 max-[767px]:[scrollbar-width:none] max-[767px]:[&::-webkit-scrollbar]:hidden">
    <div className="flex justify-center px-4 py-6 max-[767px]:p-0"><div className="w-full max-w-[800px] rounded-sm bg-bg-page shadow-md" style={{ transform: `scale(${zoomLevel / 100})`, transformOrigin: 'top center' }}>
      <MarkdownBody content={state.data || locale.empty} className="p-10 max-[767px]:p-4" />
    </div></div>
  </div>;
}
