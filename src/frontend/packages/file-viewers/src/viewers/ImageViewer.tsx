import { useState } from 'react';
import type { PreviewViewerProps } from '../viewerTypes';
import { PreviewState } from './PreviewState';
export function ImageViewer(props: PreviewViewerProps) {
  return <ImagePreview key={props.resource.previewUrl || props.resource.originalUrl} {...props} />;
}
function ImagePreview({ resource, zoomLevel = 100, locale, onError }: PreviewViewerProps) {
  const url = resource.previewUrl || resource.originalUrl;
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  if (failedUrl === url) return <PreviewState loading={false} locale={locale} />;
  return <div className="scrollbar-os flex-1 overflow-auto bg-[#fbfbfb]"><div className="flex min-h-full items-center justify-center p-8">
    <img key={url} src={url} alt={locale.imageAlt} onError={() => { setFailedUrl(url); onError?.(new Error('Image preview failed')); }} className="max-w-full rounded-sm shadow-md" style={{ transform: `scale(${zoomLevel / 100})`, transformOrigin: 'center center' }} />
  </div></div>;
}
