import { usePreviewResource } from '../usePreviewResource';
import type { PreviewViewerProps } from '../viewerTypes';
import { PreviewState, readPreview, usePreviewFailure } from './PreviewState';
export function TextViewer({ resource, zoomLevel = 100, locale, onError }: PreviewViewerProps) {
  const url = resource.previewUrl || resource.originalUrl;
  const state = usePreviewResource(url, async signal => (await readPreview(url, signal)).text());
  usePreviewFailure(state.error, onError);
  if (state.status !== 'ready') return <PreviewState loading={state.status === 'loading'} locale={locale} />;
  return <div className="scrollbar-os flex-1 overflow-auto bg-fill-1">
    <div className="flex justify-center px-4 py-6"><div className="w-full max-w-[800px] rounded-sm bg-bg-page shadow-md" style={{ transform: `scale(${zoomLevel / 100})`, transformOrigin: 'top center' }}>
      <pre className="whitespace-pre-wrap break-words p-10 font-mono text-sm leading-relaxed text-text-1">{state.data || locale.empty}</pre>
    </div></div>
  </div>;
}
