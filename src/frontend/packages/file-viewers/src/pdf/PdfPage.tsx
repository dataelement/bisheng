import { useEffect, useRef, useState, type CSSProperties } from 'react';
import type { RenderTask } from 'pdfjs-dist';
import { annotationHtml } from './annotations';
import type { PdfPageMetrics, PdfPageProps } from './types';
export function PdfPage({ pdfDoc, pageIndex, width, zoomLevel = 100, drawText = false, drawAnnotations = false, pixelRatio = 1.5, onMetrics, onError, renderOverlay }: PdfPageProps) {
  const canvasHost = useRef<HTMLDivElement>(null);
  const textLayer = useRef<HTMLDivElement>(null);
  const annotationLayer = useRef<HTMLDivElement>(null);
  const mounted = useRef(false);
  const currentDocument = useRef(pdfDoc);
  currentDocument.current = pdfDoc;
  const callbacks = useRef({ onMetrics, onError });
  callbacks.current = { onMetrics, onError };
  const [state, setState] = useState<{ document: typeof pdfDoc; metrics: PdfPageMetrics } | null>(null);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    if (width <= 0) return;
    let active = true;
    let task: RenderTask | undefined;
    let textTask: { cancel?: () => void; promise?: Promise<void> } | undefined;
    const report = callbacks.current.onError;
    const canvas = document.createElement('canvas');
    canvasHost.current?.replaceChildren(canvas);
    textLayer.current?.replaceChildren();
    annotationLayer.current?.replaceChildren();
    void (async () => {
      try {
        const page = await pdfDoc.getPage(pageIndex + 1);
        if (!active) return;
        const original = page.getViewport({ scale: 1 });
        const scale = width / original.width * zoomLevel / 100;
        const metrics = { pageIndex, originalWidth: original.width, originalHeight: original.height, width: original.width * scale, height: original.height * scale, scale };
        const viewport = page.getViewport({ scale: scale * pixelRatio });
        canvas.width = viewport.width;
        canvas.height = viewport.height;
        canvas.style.width = `${metrics.width}px`;
        canvas.style.height = `${metrics.height}px`;
        setState({ document: pdfDoc, metrics });
        callbacks.current.onMetrics?.(metrics);
        const context = canvas.getContext('2d');
        if (!context) throw new Error('Canvas context unavailable');
        task = page.render({ canvasContext: context, viewport });
        await task.promise;
        if (!active) return;
        if (drawText && textLayer.current) {
          const pdfjs = await import('pdfjs-dist');
          const content = await page.getTextContent();
          if (!active || !textLayer.current) return;
          textTask = pdfjs.renderTextLayer({ textContentSource: content, container: textLayer.current, viewport: page.getViewport({ scale }), textDivs: [] });
          await textTask.promise;
        }
        if (drawAnnotations && annotationLayer.current) {
          const annotations: unknown[] = await page.getAnnotations();
          if (!active || !annotationLayer.current) return;
          for (const value of annotations) {
            if (!value || typeof value !== 'object') continue;
            const item = value as Record<string, unknown>;
            if (item.subtype !== 'FreeText' || !Array.isArray(item.rect) || !item.richText || typeof item.richText !== 'object') continue;
            const rect = item.rect;
            if (rect.length !== 4 || !rect.every(coordinate => typeof coordinate === 'number' && Number.isFinite(coordinate))) continue;
            const element = document.createElement('div');
            element.innerHTML = annotationHtml((item.richText as Record<string, unknown>).html);
            Object.assign(element.style, { position: 'absolute', left: `${Number(rect[0]) * scale}px`, top: `${(original.height - Number(rect[3])) * scale - 4}px`, transformOrigin: 'top left', transform: `scale(${scale})` });
            annotationLayer.current.appendChild(element);
          }
        }
      } catch (error) {
        if (!mounted.current || currentDocument.current !== pdfDoc) return;
        if (error && typeof error === 'object' && 'name' in error && error.name === 'RenderingCancelledException') return;
        report?.(error);
      }
    })();
    return () => { active = false; task?.cancel?.(); textTask?.cancel?.(); };
  }, [pdfDoc, pageIndex, width, zoomLevel, drawText, drawAnnotations, pixelRatio]);
  const metrics = state?.document === pdfDoc ? state.metrics : null;
  return <div data-pdf-page={pageIndex} className="relative overflow-hidden bg-white" style={{ width: metrics?.width ?? width, height: metrics?.height, '--scale-factor': metrics?.scale ?? 1 } as CSSProperties}>
    <div ref={canvasHost} />
    <div ref={textLayer} className="textLayer absolute inset-0 z-20 origin-top-left overflow-hidden leading-none opacity-25" />
    <div ref={annotationLayer} className="pointer-events-none absolute inset-0 z-20 origin-top-left overflow-hidden" />
    {metrics && renderOverlay?.(metrics)}
  </div>;
}
