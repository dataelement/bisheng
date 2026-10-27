import { HtmlViewer as SharedHtmlViewer } from '@bisheng/file-viewers/html-viewer';
import { usePreviewLocale } from '@bisheng/file-viewers/locale';
import { resolveKnowledgePreviewUrl } from '../previewUrlUtils';
interface HtmlViewerProps { fileUrl: string; zoomLevel: number }
export function HtmlViewer({ fileUrl, zoomLevel }: HtmlViewerProps) {
  const locale = usePreviewLocale();
  const url = resolveKnowledgePreviewUrl(fileUrl);
  return <SharedHtmlViewer resource={{ originalUrl: url, previewUrl: url }} zoomLevel={zoomLevel} locale={locale} />;
}
