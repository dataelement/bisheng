import { sanitizeOoXml, serializeOoXmlElement } from './pptx-resources.js';

const child = (node, name) => [...(node?.children ?? [])].find(item => item.localName === name);
const visualTypes = new Set(['sp', 'pic', 'cxnSp', 'grpSp', 'graphicFrame', 'contentPart']);
const metadataTypes = new Set(['nvGrpSpPr', 'grpSpPr', 'extLst']);
const first = (node, name) => node.getElementsByTagNameNS('*', name)[0];

/** Select an explicit compatibility branch before the parser enumerates slide objects. */
export function resolvePptxAlternatives(xml) {
  if(!/<(?:[A-Za-z_][\w.-]*:)?AlternateContent(?:\s|>)/u.test(xml))return {xml,count:0};
  const doc = new DOMParser().parseFromString(sanitizeOoXml(xml), 'application/xml');
  if (doc.querySelector('parsererror')) throw new Error('PPTX 页面 XML 无效');
  const tree = first(doc, 'spTree');
  let count = 0;
  function walk(parent, depth) {
    if (depth > 64) throw new Error('PPTX 兼容分支层级超过解析限制');
    for (const node of [...parent.children]) {
      if (node.localName === 'AlternateContent') {
        const branch = child(node, 'Fallback') ?? child(node, 'Choice');
        if (branch) {
          walk(branch, depth + 1);
          for (const item of [...branch.children]) parent.insertBefore(item, node);
          node.remove(); count++;
        }
      } else if (node.localName === 'grpSp') walk(node, depth + 1);
    }
  }
  if (tree) walk(tree, 0);
  return { xml: count ? serializeOoXmlElement(doc.documentElement) : xml, count };
}

/** Enumerate source painter order independently of the renderer's supported node types. */
export function pptxObjectInventory(xml) {
  const doc = new DOMParser().parseFromString(xml, 'application/xml');
  if (doc.querySelector('parsererror')) throw new Error('PPTX 页面 XML 无效');
  const tree = first(doc, 'spTree');
  return [...(tree?.children ?? [])].filter(node => visualTypes.has(node.localName) || !metadataTypes.has(node.localName)).map((source, index) => {
    const identity = first(source, 'cNvPr');
    const xf = child(child(source, 'spPr'), 'xfrm') ?? child(source, 'xfrm');
    const off = child(xf, 'off'), ext = child(xf, 'ext');
    const coordinates = ['x', 'y', 'cx', 'cy'].map((key, i) => Number((i < 2 ? off : ext)?.getAttribute(key) ?? NaN));
    const graphic = child(child(source, 'graphic'), 'graphicData');
    const uri = graphic?.getAttribute('uri') ?? '';
    const feature = uri.includes('diagram') ? 'smartart' : uri.includes('ole') ? 'embedded-object' : uri.includes('chart') ? 'chart' : source.localName;
    return {
      id: identity?.getAttribute('id') ?? `source-${index + 1}`,
      name: identity?.getAttribute('name') ?? feature,
      nodeType: 'unconverted', feature,
      position: { x: coordinates[0] / 9525, y: coordinates[1] / 9525 },
      size: { w: coordinates[2] / 9525, h: coordinates[3] / 9525 },
      rotation: Number(xf?.getAttribute('rot') ?? 0) / 60000,
      flipH: ['1', 'true'].includes(xf?.getAttribute('flipH')),
      flipV: ['1', 'true'].includes(xf?.getAttribute('flipV')),
      positioned: coordinates.every(Number.isFinite) && coordinates[2] >= 0 && coordinates[3] >= 0
    };
  });
}
