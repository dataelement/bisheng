import { TextViewer as SharedTextViewer } from '@bisheng/file-viewers/text';
import { usePreviewLocale } from '@bisheng/file-viewers/locale';
interface TextViewerProps { fileUrl: string; zoomLevel: number }
export function TextViewer({ fileUrl, zoomLevel }: TextViewerProps) {
  const locale = usePreviewLocale();
  const url = fileUrl;
  return <SharedTextViewer resource={{ originalUrl: url, previewUrl: url }} zoomLevel={zoomLevel} locale={locale} />;
}
