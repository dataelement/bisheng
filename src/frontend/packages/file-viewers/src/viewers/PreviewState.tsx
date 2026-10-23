import { useEffect, useRef } from 'react';
import type { PreviewViewerProps } from '../viewerTypes';
export function usePreviewFailure(error: unknown, onError?: (error: unknown) => void) {
  const onErrorRef = useRef(onError);
  onErrorRef.current = onError;
  useEffect(() => { if (error !== undefined) onErrorRef.current?.(error); }, [error]);
}
export function PreviewState({ loading, locale }: Pick<PreviewViewerProps, 'locale'> & { loading: boolean }) {
  return <div role={loading ? 'status' : 'alert'} className="flex min-h-0 flex-1 items-center justify-center px-4 text-sm text-text-3">{loading ? locale.loading : locale.failed}</div>;
}
export async function readPreview(url: string, signal: AbortSignal): Promise<Response> {
  const response = await fetch(url, { signal });
  if (!response.ok) throw Object.assign(new Error('Preview read failed'), { status: response.status, response });
  return response;
}
