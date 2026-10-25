import { useState } from 'react';
import type { PreviewViewerProps } from '../viewerTypes';
import { MediaPlayer } from './MediaPlayer';
import { MediaTranscriptTabs } from './MediaTranscriptTabs';
import { PreviewState } from './PreviewState';
export interface MediaViewerProps extends PreviewViewerProps {
  kind: 'audio' | 'video';
  allowDownload?: boolean;
  onDownload?: () => void;
}
export function MediaViewer(props: MediaViewerProps) {
  return <MediaPreview key={JSON.stringify([props.kind,props.resource.originalUrl,props.resource.previewUrl])} {...props} />;
}
function MediaPreview({ resource, kind, locale, onError, allowDownload = false, onDownload }: MediaViewerProps) {
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  if (failedUrl === resource.originalUrl) return <PreviewState loading={false} locale={locale} />;
  const transcript = resource.previewUrl && resource.previewUrl !== resource.originalUrl;
  return <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-[#fbfbfb]">
    <div className={`shrink-0 p-4 ${transcript ? '' : 'flex-1'}`}>
      <MediaPlayer key={resource.originalUrl} kind={kind} src={resource.originalUrl} labels={locale.media} selectLabels={locale.select} allowDownload={allowDownload} onDownload={onDownload}
        onError={error => { setFailedUrl(resource.originalUrl); onError?.(error); }} />
    </div>
    {transcript && <><div className="h-px shrink-0 bg-border-base" /><div className="flex min-h-0 min-w-0 flex-1 flex-col">
      <MediaTranscriptTabs key={resource.previewUrl} resource={resource} locale={locale} onError={onError} />
    </div></>}
  </div>;
}
