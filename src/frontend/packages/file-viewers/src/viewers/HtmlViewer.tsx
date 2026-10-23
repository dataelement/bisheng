import { ARTIFACT_SANDBOX, buildSandboxedSrcDoc, focusArtifactFrame } from '../html/sandboxedHtml';
import { usePreviewResource } from '../usePreviewResource';
import type { PreviewViewerProps } from '../viewerTypes';
import { PreviewState, readPreview, usePreviewFailure } from './PreviewState';
export function HtmlViewer({ resource, zoomLevel = 100, locale, onError }: PreviewViewerProps) {
  const url = resource.previewUrl || resource.originalUrl;
  const state = usePreviewResource(url, async signal => (await readPreview(url, signal)).text());
  usePreviewFailure(state.error, onError);
  if (state.status !== 'ready') return <PreviewState loading={state.status === 'loading'} locale={locale} />;
  const scale = zoomLevel / 100;
  return <div className="scrollbar-os flex-1 overflow-auto bg-[#fbfbfb]"><div className="h-full w-full">
    <iframe key={url} srcDoc={buildSandboxedSrcDoc(state.data || '')} title={locale.htmlTitle} sandbox={ARTIFACT_SANDBOX} onLoad={event => focusArtifactFrame(event.currentTarget)} className="h-full w-full border-none bg-white" style={{ transform: `scale(${scale})`, transformOrigin: 'top left', width: `${100 / scale}%`, height: `${100 / scale}%` }} />
  </div></div>;
}
