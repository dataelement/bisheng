export interface Box { x: number; y: number; width: number; height: number }
export interface PageSize { width: number; height: number }
export interface PageLayout { top: number; height: number; scale: number }
export function pageIndexFromMetadata(page: number, base: 0 | 1, count: number): number | null {
  const index = page - base;
  return Number.isInteger(index) && index >= 0 && index < count ? index : null;
}
export function pageLayout(sizes: PageSize[], width: number): PageLayout[] {
  let top = 0;
  return sizes.map(size => {
    const scale = width / size.width;
    const height = size.height * scale;
    const page = { top, height, scale };
    top += height;
    return page;
  });
}
export function scaleBBox(bbox: [number, number, number, number], scale: number): Box {
  const [x1, y1, x2, y2] = bbox;
  return { x: x1 * scale, y: y1 * scale, width: (x2 - x1) * scale, height: (y2 - y1) * scale };
}
export function containsBBox(outer: Box, inner: Box): boolean {
  return outer.x <= inner.x && outer.y <= inner.y && outer.x + outer.width >= inner.x + inner.width && outer.y + outer.height >= inner.y + inner.height;
}
