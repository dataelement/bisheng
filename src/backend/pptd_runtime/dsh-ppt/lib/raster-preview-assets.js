import sharp from 'sharp';

const MAX_EMBEDDED_BYTES = 6 * 1024 * 1024;
const MAX_PREVIEW_EDGE = 4096;

/** Frame-sized raster copies keep SVG attributes bounded while source/export assets retain their bytes. */
export async function preparePreviewProject(project, pageIndex, scale) {
  const page = project.pages[pageIndex];
  if (!page) throw new Error(`PPTD page ${pageIndex + 1} does not exist`);
  const assets = new Map(project.source.assets);
  const elements = [];
  const cache = new Map();
  for (const element of page.elements) {
    const key = element.elementType === 'image' && typeof element.src === 'string' ? element.src.replace(/^\.\//u, '') : undefined;
    const asset = assets.get(key);
    if (!asset || asset.bytes.length <= 1024 * 1024 || !/^image\/(png|jpeg|webp|gif)$/.test(asset.mediaType)) {
      elements.push(element);
      continue;
    }
    const fit = ['contain', 'fill'].includes(element.fit?.mode) ? element.fit.mode : 'cover';
    const edge = Math.max(...element.bounds.slice(2)) * scale;
    const ratio = Math.min(1, MAX_PREVIEW_EDGE / edge);
    let width = Math.max(1, Math.ceil(element.bounds[2] * scale * ratio));
    let height = Math.max(1, Math.ceil(element.bounds[3] * scale * ratio));
    const spec = JSON.stringify([key, width, height, fit]);
    let previewKey = cache.get(spec);
    if (!previewKey) {
      // Separate keys allow the same source image to be shown in different frame shapes.
      previewKey = `__preview-${pageIndex}-${elements.length}`;
      while (assets.has(previewKey)) previewKey += '-';
      const input = sharp(Buffer.from(asset.bytes));
      const metadata = await input.metadata();
      const opaque = fit !== 'contain' && (!metadata.hasAlpha || (await input.stats()).isOpaque);
      let bytes;
      do {
        const resized = input.clone().resize({ width, height, fit, background: { r: 0, g: 0, b: 0, alpha: 0 } });
        bytes = await (opaque ? resized.removeAlpha().jpeg({ quality: 95 }) : resized.png()).toBuffer();
        if (bytes.length <= MAX_EMBEDDED_BYTES) break;
        const shrink = Math.min(0.8, Math.sqrt(MAX_EMBEDDED_BYTES / bytes.length) * 0.9);
        width = Math.max(1, Math.floor(width * shrink));
        height = Math.max(1, Math.floor(height * shrink));
      } while (true);
      assets.set(previewKey, { ...asset, bytes, mediaType: opaque ? 'image/jpeg' : 'image/png' });
      cache.set(spec, previewKey);
    }
    elements.push({ ...element, src: previewKey });
  }
  const pages = project.pages.map((item, index) => index === pageIndex ? { ...item, elements } : item);
  return { ...project, pages, source: { ...project.source, assets } };
}
