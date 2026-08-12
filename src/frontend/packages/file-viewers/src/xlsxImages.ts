import { MIME_TYPES } from './sheetUtils';
import type { ExtractedImage, ImageAnchor, SheetImageIndex } from './types';

const EMU_PER_PX = 914400 / 96;
const RELS_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships';
const IMAGE_EXTENSIONS = ['png', 'jpg', 'jpeg', 'gif', 'bmp', 'tiff', 'tif', 'jfif'];

interface ZipEntry {
  dir: boolean;
  async(type: 'base64' | 'text'): Promise<string>;
}

/** Minimal shape of the JSZip instance that xlsx-populate keeps on the workbook. */
export interface ZipLike {
  file(path: string): ZipEntry | null;
  forEach(callback: (relativePath: string, entry: ZipEntry) => void): void;
}

function dirOf(path: string): string {
  const index = path.lastIndexOf('/');
  return index === -1 ? '' : path.slice(0, index);
}

/** Resolve an OPC relationship target (often "../drawings/x.xml") into a package path. */
function resolvePath(baseDir: string, target: string): string {
  if (target.startsWith('/')) return target.replace(/^\/+/, '');
  const segments = baseDir ? baseDir.split('/') : [];
  for (const part of target.split('/')) {
    if (part === '' || part === '.') continue;
    if (part === '..') segments.pop();
    else segments.push(part);
  }
  return segments.join('/');
}

function relsPathFor(partPath: string): string {
  const dir = dirOf(partPath);
  const name = dir ? partPath.slice(dir.length + 1) : partPath;
  return `${dir ? `${dir}/` : ''}_rels/${name}.rels`;
}

/**
 * Namespace prefixes in OOXML are arbitrary — "xdr:" is a convention, not a rule.
 * Always match on local name so files from WPS/report exporters still parse.
 */
function tags(root: Document | Element, localName: string): Element[] {
  return Array.from(root.getElementsByTagNameNS('*', localName));
}

function relAttr(element: Element, name: string): string | null {
  return element.getAttributeNS(RELS_NS, name) ?? element.getAttribute(`r:${name}`);
}

async function readXml(zip: ZipLike, path: string): Promise<Document | null> {
  const entry = zip.file(path);
  if (!entry) return null;
  const xml = await entry.async('text');
  const doc = new DOMParser().parseFromString(xml, 'text/xml');
  return doc.getElementsByTagName('parsererror').length > 0 ? null : doc;
}

async function readRelationships(
  zip: ZipLike,
  partPath: string,
): Promise<Record<string, { type: string; target: string }>> {
  const map: Record<string, { type: string; target: string }> = {};
  const doc = await readXml(zip, relsPathFor(partPath));
  if (!doc) return map;

  const baseDir = dirOf(partPath);
  for (const rel of tags(doc, 'Relationship')) {
    const id = rel.getAttribute('Id');
    const target = rel.getAttribute('Target');
    if (!id || !target || rel.getAttribute('TargetMode') === 'External') continue;
    map[id] = { type: rel.getAttribute('Type') ?? '', target: resolvePath(baseDir, target) };
  }
  return map;
}

function readMarker(anchor: Element, localName: 'from' | 'to'): { col: number; row: number } | null {
  const marker = tags(anchor, localName)[0];
  if (!marker) return null;
  const col = parseInt(tags(marker, 'col')[0]?.textContent ?? '', 10);
  const row = parseInt(tags(marker, 'row')[0]?.textContent ?? '', 10);
  if (Number.isNaN(col) || Number.isNaN(row)) return null;
  return { col, row };
}

function readExtent(anchor: Element): { w: number; h: number } | undefined {
  const ext = tags(anchor, 'ext')[0];
  if (!ext) return undefined;
  const cx = Number(ext.getAttribute('cx'));
  const cy = Number(ext.getAttribute('cy'));
  if (!Number.isFinite(cx) || !Number.isFinite(cy) || cx <= 0 || cy <= 0) return undefined;
  return { w: Math.round(cx / EMU_PER_PX), h: Math.round(cy / EMU_PER_PX) };
}

const ANCHOR_KINDS: Array<{ tag: string; floating: boolean }> = [
  { tag: 'twoCellAnchor', floating: false },
  { tag: 'oneCellAnchor', floating: false },
  // Absolute anchors are positioned in EMU over the grid, with no cell to sit in.
  { tag: 'absoluteAnchor', floating: true },
];

async function parseDrawingAnchors(zip: ZipLike, drawingPath: string, mediaIds: Set<string>): Promise<ImageAnchor[]> {
  const anchors: ImageAnchor[] = [];
  try {
    const doc = await readXml(zip, drawingPath);
    if (!doc) return anchors;
    const rels = await readRelationships(zip, drawingPath);

    for (const kind of ANCHOR_KINDS) {
      for (const anchor of tags(doc, kind.tag)) {
        const blip = tags(anchor, 'blip')[0];
        const rId = blip ? relAttr(blip, 'embed') : null;
        const target = rId ? rels[rId]?.target : undefined;
        if (!target) continue;

        const imageId = target.split('/').pop() ?? target;
        if (!mediaIds.has(imageId)) continue;

        const from = readMarker(anchor, 'from');
        anchors.push({
          imageId,
          from: from ?? { col: 0, row: 0 },
          to: readMarker(anchor, 'to') ?? undefined,
          sizePx: readExtent(anchor),
          floating: kind.floating || !from,
        });
      }
    }
  } catch (e) {
    console.warn('[ExcelPreview] failed to parse drawing:', drawingPath, e);
  }
  return anchors;
}

/**
 * Collect every embedded picture and the sheet it is anchored to.
 *
 * The sheet a drawing belongs to is only discoverable through the relationship
 * chain — workbook.xml (r:id) -> workbook.xml.rels -> worksheets/sheetN.xml ->
 * sheetN.xml.rels -> drawings/drawingM.xml. Sheet order and file numbering are
 * unrelated (deleting a sheet leaves gaps), so never pair them positionally.
 */
export async function extractSheetImages(zip: ZipLike): Promise<{
  images: ExtractedImage[];
  index: SheetImageIndex;
}> {
  const pending: Array<{ id: string; path: string; ext: string; base64Promise: Promise<string> }> = [];
  zip.forEach((relativePath, entry) => {
    if (!relativePath.startsWith('xl/media/') || entry.dir) return;
    const ext = relativePath.split('.').pop()?.toLowerCase() || '';
    if (!IMAGE_EXTENSIONS.includes(ext)) return;
    const id = relativePath.split('/').pop() || relativePath;
    pending.push({ id, path: relativePath, ext, base64Promise: entry.async('base64') });
  });

  const index: SheetImageIndex = {};
  const mediaIds = new Set(pending.map((img) => img.id));

  if (mediaIds.size > 0) {
    const workbook = await readXml(zip, 'xl/workbook.xml');
    const workbookRels = workbook ? await readRelationships(zip, 'xl/workbook.xml') : {};

    for (const sheetEl of workbook ? tags(workbook, 'sheet') : []) {
      const name = sheetEl.getAttribute('name');
      const rId = relAttr(sheetEl, 'id');
      const sheetPath = rId ? workbookRels[rId]?.target : undefined;
      if (!name || !sheetPath) continue;

      const sheetRels = await readRelationships(zip, sheetPath);
      const drawing = Object.values(sheetRels).find((rel) => rel.type.endsWith('/drawing'));
      if (!drawing) continue;

      const anchors = await parseDrawingAnchors(zip, drawing.target, mediaIds);
      if (anchors.length > 0) index[name] = anchors;
    }
  }

  const images: ExtractedImage[] = [];
  for (const img of pending) {
    images.push({
      id: img.id,
      path: img.path,
      ext: img.ext,
      base64: await img.base64Promise,
      mimeType: MIME_TYPES[img.ext] || 'image/png',
    });
  }

  return { images, index };
}
