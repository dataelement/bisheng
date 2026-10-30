/**
 * Markdown "download original" with its images.
 *
 * A task-mode md references workspace images by path (`![](charts/a.png)`),
 * which resolve only inside the run's workspace — downloaded alone, the file
 * opens with broken images. When the md references a local image, the backend
 * packs md + images into a zip with rewritten paths; an md without local images
 * keeps the plain single-file download.
 */
import { getMdBundle } from '~/api/linsight';
import { type ArtifactBlobOptions, type ArtifactFile, fetchArtifactBlob } from './artifactUtils';

// Same patterns as the backend's md_image_refs (markdown image + <img src>).
const MD_IMAGE_RE = /!\[[^\]]*\]\(\s*<?([^)\s>]+)/g;
const HTML_IMG_RE = /<img\b[^>]*?\bsrc\s*=\s*["']([^"']+)/gi;
const SCHEME_RE = /^[a-zA-Z][a-zA-Z0-9+.-]*:/;

/** True when the md references at least one image by path (not http/data). */
export function hasLocalImageRefs(md: string): boolean {
  return [MD_IMAGE_RE, HTML_IMG_RE].some((re) =>
    Array.from(md.matchAll(re)).some((m) => !SCHEME_RE.test(m[1])),
  );
}

function saveBlob(blob: Blob, fileName: string): void {
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = fileName;
  link.click();
  URL.revokeObjectURL(link.href);
}

/** The convert/bundle endpoints answer errors as a JSON body with HTTP 200. */
async function throwIfErrorBlob(blob: Blob): Promise<void> {
  if (!blob.type.includes('application/json')) return;
  let message = '';
  try {
    const data = JSON.parse(await blob.text());
    if (data.status_code && data.status_code !== 200) message = data.status_message || 'download failed';
  } catch {
    return;
  }
  if (message) throw new Error(message);
}

/**
 * Download a markdown deliverable; returns 'zip' when it went out bundled with
 * its images, 'md' when it was saved as the single file.
 */
export async function downloadMarkdownArtifact(
  file: ArtifactFile,
  versionId: string,
  options?: ArtifactBlobOptions,
): Promise<'md' | 'zip'> {
  const { blob, fileName } = await fetchArtifactBlob(file, versionId, options);
  if (!hasLocalImageRefs(await blob.text())) {
    saveBlob(blob, fileName);
    return 'md';
  }
  const res = await getMdBundle({
    session_version_id: versionId,
    file_url: file.file_url,
    file_name: file.file_name,
  });
  await throwIfErrorBlob(res);
  if (res.type.includes('zip')) {
    saveBlob(res, `${file.file_name.replace(/\.(md|markdown)$/i, '')}.zip`);
    return 'zip';
  }
  saveBlob(res, fileName);
  return 'md';
}
