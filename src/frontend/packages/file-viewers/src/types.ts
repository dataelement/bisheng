export type SheetData = string[][];

export interface ExtractedImage {
  id: string;
  path: string;
  ext: string;
  base64: string;
  mimeType: string;
}

/** Anchor of one picture, in original 0-based Excel coordinates. */
export interface ImageAnchor {
  /** Media file name inside xl/media, e.g. "image1.png". */
  imageId: string;
  from: { col: number; row: number };
  /** Present on twoCellAnchor only. */
  to?: { col: number; row: number };
  /** Display size in CSS pixels, converted from the EMU extent. */
  sizePx?: { w: number; h: number };
  /** absoluteAnchor pictures float over the grid and have no cell to sit in. */
  floating: boolean;
}

/**
 * Picture anchors keyed by sheet name. A picture belongs to exactly one sheet —
 * keeping the index flat (address -> image) leaks pictures across every sheet.
 */
export type SheetImageIndex = Record<string, ImageAnchor[]>;

/**
 * cleanData() drops blank rows/columns, so rendered indexes no longer match the
 * addresses drawing anchors use. The maps translate back to original coordinates.
 */
export interface CleanedSheet {
  data: SheetData;
  /** rowMap[renderedRowIndex] = original 0-based row */
  rowMap: number[];
  /** colMap[renderedColIndex] = original 0-based column */
  colMap: number[];
}

/** An anchor paired with the media it resolves to. */
export interface ResolvedImage {
  image: ExtractedImage;
  anchor: ImageAnchor;
}
