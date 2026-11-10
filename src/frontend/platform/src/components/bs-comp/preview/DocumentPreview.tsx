import { DocxViewer } from '@bisheng/file-viewers/docx';
import { TextViewer } from '@bisheng/file-viewers/text';
import { MarkdownViewer } from '@bisheng/file-viewers/markdown';
import { HtmlViewer } from '@bisheng/file-viewers/html-viewer';
import { ImageViewer } from '@bisheng/file-viewers/image';
import { MediaViewer } from '@bisheng/file-viewers/media';
import { MediaPlayer, type MediaPlayerProps } from '@bisheng/file-viewers/media-player';
import { usePreviewLocale } from '@bisheng/file-viewers/locale';
interface FilePreviewProps { filePath: string }
interface TextPreviewProps extends FilePreviewProps { html?: boolean; markdown?: boolean }
function resource(filePath: string) {
  const url = filePath.replace(/https?:\/\/[^/]+/, __APP_ENV__.BASE_URL);
  return { originalUrl: url, previewUrl: url };
}
export function PlatformDocxPreview({ filePath }: FilePreviewProps) {
  const locale = usePreviewLocale();
  if (filePath.split('?')[0].split('#')[0].toLowerCase().endsWith('.doc')) return <div className="flex h-full min-h-0 items-center justify-center text-text-3">{locale.unsupported}</div>;
  return <div className="flex h-full min-h-0 flex-col"><DocxViewer resource={resource(filePath)} locale={locale} /></div>;
}
export function PlatformTextPreview({ filePath, html, markdown }: TextPreviewProps) {
  const locale = usePreviewLocale();
  const Viewer = html ? HtmlViewer : markdown ? MarkdownViewer : TextViewer;
  return <div className="flex h-full min-h-0 flex-col"><Viewer resource={resource(filePath)} locale={locale} /></div>;
}
export function PlatformImagePreview({ filePath }: FilePreviewProps) {
  const locale = usePreviewLocale();
  return <div className="flex h-full min-h-0 flex-col"><ImageViewer resource={resource(filePath)} locale={locale} /></div>;
}
interface MediaPreviewProps { fileUrl: string; transcriptUrl: string; isVideo: boolean }
export function PlatformMediaPreview({ fileUrl, transcriptUrl, isVideo }: MediaPreviewProps) {
  const locale = usePreviewLocale();
  return <MediaViewer key={fileUrl} resource={{ originalUrl: fileUrl, previewUrl: transcriptUrl }} kind={isVideo ? 'video' : 'audio'} locale={locale} />;
}
interface HostMediaPlayerProps extends Omit<MediaPlayerProps, 'labels' | 'selectLabels'> { src: string }
export function PlatformMediaPlayer(props: HostMediaPlayerProps) {
  const locale = usePreviewLocale();
  return <MediaPlayer {...props} labels={locale.media} selectLabels={locale.select} />;
}
