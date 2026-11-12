const A = 'http://schemas.openxmlformats.org/drawingml/2006/main';
const edges = { left: 'l', top: 't', right: 'r', bottom: 'b' };
/** Crop percentages are signed fractions of the source image, including padding. */
export function imageCropIssue(crop) {
  if (!crop || typeof crop !== 'object' || Array.isArray(crop) || Object.keys(crop).some(key => !(key in edges))) return '图片裁剪应包含四边比例。';
  const values = Object.keys(edges).map(key => crop[key] ?? 0);
  if (values.some(value => typeof value !== 'number' || !Number.isFinite(value) || Math.abs(value * 100000) > 2147483647)) return '图片裁剪比例应为有界数值。';
  if (values[0] + values[2] >= 1 || values[1] + values[3] >= 1) return '图片裁剪应保留有效的源图区域。';
}
/** Apply the current model crop to native editable pictures after image packaging. */
export function restoreImageCrops(doc, elements) {
  const pictures = new Map([...doc.getElementsByTagNameNS('*', 'pic')].map(pic => [pic.getElementsByTagNameNS('*', 'cNvPr')[0]?.getAttribute('name'), pic]));
  for (const element of elements) {
    if (element.elementType !== 'image' || element.crop === undefined) continue;
    const issue = imageCropIssue(element.crop); if (issue) throw new Error(issue);
    const pic = pictures.get(element.elementId), fill = pic && [...pic.children].find(node => node.localName === 'blipFill');
    if (!fill) throw new Error(`Missing editable cropped picture: ${element.elementId}`);
    [...fill.children].filter(node => node.localName === 'srcRect').forEach(node => node.remove());
    const source = doc.createElementNS(A, 'a:srcRect');
    for (const [key, name] of Object.entries(edges)) source.setAttribute(name, String(Math.round((element.crop[key] ?? 0) * 100000)));
    fill.insertBefore(source, [...fill.children].find(node => ['tile', 'stretch'].includes(node.localName)) ?? null);
  }
}
