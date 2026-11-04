import type { PDFDocumentProxy } from 'pdfjs-dist';
import { usePreviewResource } from '../usePreviewResource';

interface PdfAssets { workerUrl: string; cMapUrl: string }
export function usePdfDocument(url: string, assets: PdfAssets) {
  const key = url ? JSON.stringify([url, assets.workerUrl, assets.cMapUrl]) : '';
  const state = usePreviewResource<PDFDocumentProxy>(key, async signal => {
    const pdfjs = await import('pdfjs-dist');
    if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
    pdfjs.GlobalWorkerOptions.workerSrc = assets.workerUrl;
    const task = pdfjs.getDocument({ url, cMapUrl: assets.cMapUrl, cMapPacked: true });
    let destroyed = false;
    const destroy = () => {
      if (destroyed) return;
      destroyed = true;
      void task.destroy().catch(() => undefined);
    };
    signal.addEventListener('abort', destroy, { once: true });
    try {
      return await task.promise;
    } catch (error) {
      signal.removeEventListener('abort', destroy);
      destroy();
      throw error;
    }
  });
  return { status: state.status, document: state.data ?? null, error: state.error };
}
