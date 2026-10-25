import { useEffect, useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import DialogImage from './DialogImage';
export function CompactMarkdownImage({ src, alt, title }: { src?: string; alt?: string; title?: string }) {
  if (!src) return null;
  return (
    <Dialog.Root>
      {/* not-prose: the prose sheet's 2em image margins sit later in the
          stylesheet than the utilities and would win the tie otherwise. */}
      <span className="not-prose my-3 block">
        <Dialog.Trigger asChild>
          <img
            src={src}
            alt={alt ?? ''}
            title={title}
            loading="lazy"
            className="block max-h-[320px] max-w-[min(60%,480px)] cursor-zoom-in rounded-lg object-contain"
          />
        </Dialog.Trigger>
      </span>
      <DialogImage src={src} />
    </Dialog.Root>
  );
}

// Absolute / already-loadable image src (http(s), protocol-relative, data:/blob:,
// root-relative). Anything else is a bare relative ref that must be resolved.
const ABSOLUTE_IMAGE_SRC_RE = /^(https?:)?\/\/|^(data|blob):|^\//i;

/**
 * Image renderer for markdown deliverables whose figures are authored as relative
 * refs (`![alt](charts/x.png)`). The client pipeline resolves relative refs via an
 * injected async `resolveImageSrc` (workspace file-list → presigned URL); absolute
 * srcs render straight through. Used ONLY when `resolveImageSrc` is provided (the
 * Linsight artifact preview); chat bubbles pass no resolver and keep the default
 * react-markdown <img>, so their behaviour is unchanged.
 */
export function MarkdownImage({
  src,
  alt,
  title,
  resolveImageSrc,
}: {
  src?: string;
  alt?: string;
  title?: string;
  resolveImageSrc: (src: string) => Promise<string | null>;
}) {
  const isAbsolute = !!src && ABSOLUTE_IMAGE_SRC_RE.test(src);
  const [resolved, setResolved] = useState<string | null>(isAbsolute ? (src as string) : null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!src) {
      setResolved(null);
      setFailed(true);
      return undefined;
    }
    if (isAbsolute) {
      setResolved(src);
      setFailed(false);
      return undefined;
    }
    let cancelled = false;
    setResolved(null);
    setFailed(false);
    resolveImageSrc(src)
      .then((url) => {
        if (cancelled) return;
        if (url) setResolved(url);
        else setFailed(true);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [src, isAbsolute, resolveImageSrc]);

  if (failed) {
    // Unresolvable relative ref → show the caption text instead of a broken icon.
    return <span className="text-xs text-gray-400">{alt || src}</span>;
  }
  if (!resolved) {
    // Resolving → small pulse placeholder to avoid a layout jump.
    return (
      <span
        className="my-1 inline-block h-4 w-28 animate-pulse rounded bg-gray-100 align-middle"
        aria-hidden
      />
    );
  }
  return <img src={resolved} alt={alt} title={title} className="max-w-full rounded" loading="lazy" />;
}

