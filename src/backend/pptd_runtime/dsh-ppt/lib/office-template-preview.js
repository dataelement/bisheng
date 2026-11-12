import { createConverterFactory } from '@deepseek-ai/libreoffice-kit';
import { mkdir, writeFile, copyFile, rm, stat } from 'node:fs/promises';
import path from 'node:path';
import { renderPptdProject } from './pptd.js';
import { templateOfficeFontOptions } from './office-font-options.js';
import { createOfficePreviewBatches } from './office-preview-batches.js';

const MAX_PREVIEW_BYTES = 128 * 1024 * 1024;
/** Render checked template slides through Office/PDFium. The caller owns the
 * draft directory and holds the library's policy/audit lock. Two bounded slots
 * overlap the next small PDF export with the current PDF's per-page raster notifications.
 */
export async function renderOfficeTemplatePreview(project, directory, longEdge, maxPages, onPage, signal) {
  signal?.throwIfAborted();
  if (!Number.isInteger(maxPages) || maxPages < 1 || maxPages > 200
    || !Number.isFinite(longEdge) || longEdge < 1 || !project.pages.length || project.pages.length > maxPages)
    throw new Error('Office template preview exceeds its page budget');
  const started = Date.now();
  const deck = await renderPptdProject(project);
  signal?.throwIfAborted();
  const timings = { exportMs: Date.now() - started, officeMs: 0, rasterMs: 0, firstPageMs: 0, totalMs: 0 };
  await writeFile(path.join(directory, 'preview-deck.pptx'), deck.bytes, { flag: 'wx', mode: 0o600 });
  const select = createOfficePreviewBatches(deck.bytes, project.pages.length);
  const tiles = path.join(directory, 'office-preview');
  const destination = path.join(directory, 'preview', 'pages');
  const missingFonts = new Set();
  let pdfBytes = 0, pending;
  const factory = await createConverterFactory({ timeoutMs: 120000,
    maxInputBytes: MAX_PREVIEW_BYTES, maxOutputBytes: MAX_PREVIEW_BYTES, ...templateOfficeFontOptions });
  try {
    signal?.throwIfAborted();
    const office = await factory.create(), raster = await factory.create();
    await mkdir(tiles, { recursive: true, mode: 0o700 });
    await mkdir(destination, { recursive: true, mode: 0o700 });
    const prepare = async (first, count) => {
      signal?.throwIfAborted();
      const begun = Date.now();
      const bytes = select(first, count);
      timings.exportMs += Date.now() - begun;
      const batchDirectory = path.join(tiles, `batch-${first + 1}`);
      await mkdir(batchDirectory, { mode: 0o700 });
      const inputPath = path.join(batchDirectory, 'deck.pptx'), pdf = path.join(batchDirectory, 'deck.pdf');
      await writeFile(inputPath, bytes, { flag: 'wx', mode: 0o600 });
      const officeStarted = Date.now();
      const converted = await office.render({ inputPath, outputPath: pdf },signal);
      timings.officeMs += Date.now() - officeStarted;
      for (const font of converted.missingFonts) missingFonts.add(font);
      pdfBytes += (await stat(pdf)).size;
      if (pdfBytes > MAX_PREVIEW_BYTES) throw new Error('Office template preview exceeds its PDF byte budget');
      return { first, count, directory: batchDirectory, pdf };
    };
    const paint = async batch => {
      const outputDir = path.join(batch.directory, 'pages'), rasterStarted = Date.now();
      let expected = 1;
      const pages = Array.from({ length: batch.count }, (_, index) => index + 1);
      const rendered = await raster.renderImages({ inputPath: batch.pdf, outputDir, pages,
        dpi: Math.max(24, Math.min(600, longEdge / Math.max(project.width, project.height) * 72)), maxPages },
      signal, async (image, pageCount) => {
        signal?.throwIfAborted();
        if (pageCount !== batch.count || image.page !== expected)
          throw new Error('Office template preview page count mismatch');
        const slideNumber = batch.first + expected, target = path.join(destination, `page-${slideNumber}.png`);
        await copyFile(image.path, target);
        if (slideNumber === 1) timings.firstPageMs = Date.now() - started;
        await onPage?.({ page: slideNumber, total: project.pages.length, path: target });
        expected++;
      });
      timings.rasterMs += Date.now() - rasterStarted;
      if (rendered.pageCount !== batch.count || rendered.images.length !== batch.count || expected !== batch.count + 1
        || rendered.images.some((image, index) => image.page !== index + 1))
        throw new Error('Office template preview page count mismatch');
      await rm(batch.directory, { recursive: true, force: true });
    };
    // Finish and publish the cover before starting another Office job.
    await paint(await prepare(0, 1));
    const schedule = first => prepare(first, Math.min(8, project.pages.length - first))
      .then(value => ({ value }), error => ({ error }));
    if (project.pages.length > 1) pending = schedule(1);
    while (pending) {
      const outcome = await pending;
      if (outcome.error) throw outcome.error;
      const batch = outcome.value, next = batch.first + batch.count;
      pending = next < project.pages.length ? schedule(next) : undefined;
      await paint(batch);
    }
    signal?.throwIfAborted();
    timings.totalMs = Date.now() - started;
    return { engine: 'libreoffice-pdfium', missingFonts: [...missingFonts], timings };
  } finally {
    // Disposal aborts native work; join any in-flight export before removing its files.
    try { await factory.dispose(); }
    finally { await pending; await rm(tiles, { recursive: true, force: true }); }
  }
}
