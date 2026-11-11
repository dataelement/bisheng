import path from 'node:path';
import { serializeOoXmlElement } from './pptx-resources.js';
const R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships';
const child = (node, name) => [...(node?.children ?? [])].find(item => item.localName === name);
const relPath = part => path.posix.join(path.posix.dirname(part), '_rels', path.posix.basename(part) + '.rels');
const parse = xml => new DOMParser().parseFromString(xml, 'application/xml');
const target = (part, rel) => rel.getAttribute('Target').startsWith('/') ? rel.getAttribute('Target').slice(1) : path.posix.normalize(path.posix.join(path.posix.dirname(part), rel.getAttribute('Target')));
const ownPlaceholder = node => [...node.children].filter(item => ['nvSpPr','nvPicPr','nvGrpSpPr','nvGraphicFramePr','nvCxnSpPr'].includes(item.localName)).some(item => child(child(item,'nvPr'),'ph'));
function removePlaceholders(node) {
  if (ownPlaceholder(node)) { node.remove(); return false; }
  if (node.localName === 'grpSp') for (const item of [...node.children]) removePlaceholders(item);
  return true;
}
function remapRelationships(node, mapping) {
  for (const item of [node, ...node.getElementsByTagName('*')]) for (const attr of [...item.attributes]) {
    if (attr.namespaceURI === R && mapping.has(attr.value)) item.setAttributeNS(R, attr.name, mapping.get(attr.value));
  }
}
/** Compose visible non-placeholder layers in painter order, with slide-owned relationships. */
export async function composePptxLayers(files) {
  // Layouts and masters are immutable inputs. Clone their nodes into each slide,
  // keeping relationship remapping and placeholder removal owned by that slide.
  const documents=new Map();
  const readLayer=(part,xml)=>{
    if(!documents.has(part))documents.set(part,parse(xml));
    return documents.get(part);
  };
  for (const [slidePath, xml] of files.slides) {
    // XML documents queue lifecycle callbacks. Yield so a completed page and
    // its temporary clones are released before the next page is parsed.
    await new Promise(resolve => setImmediate(resolve));
    const slide = parse(xml);
    if(slide.getElementsByTagName('parsererror').length)throw new Error('PPTX 页面 XML 无效');
    const relKey = relPath(slidePath), rels = parse(files.slideRels.get(relKey));
    const layoutRel = [...rels.documentElement.children].find(r => r.getAttribute('Type').endsWith('/slideLayout'));
    if (!layoutRel) continue;
    const layoutPath = target(slidePath, layoutRel), layoutXml = files.slideLayouts.get(layoutPath);
    if (!layoutXml) continue;
    const layout = readLayer(layoutPath,layoutXml), layoutRels = readLayer(relPath(layoutPath),files.slideLayoutRels.get(relPath(layoutPath)));
    const masterRel = [...layoutRels.documentElement.children].find(r => r.getAttribute('Type').endsWith('/slideMaster'));
    const masterPath = masterRel && target(layoutPath, masterRel);
    const master = masterPath && files.slideMasters.has(masterPath) ? readLayer(masterPath,files.slideMasters.get(masterPath)) : undefined;
    const layers = [];
    if (!['0','false'].includes(slide.documentElement.getAttribute('showMasterSp')) && !['0','false'].includes(layout.documentElement.getAttribute('showMasterSp')) && master) layers.push([masterPath, master, files.slideMasterRels]);
    layers.push([layoutPath, layout, files.slideLayoutRels]);
    const common = child(slide.documentElement, 'cSld'), tree = child(common, 'spTree');
    const anchor = [...tree.children].find(n => !['nvGrpSpPr', 'grpSpPr'].includes(n.localName));
    let sequence = 0;
    const layerMappings = new Map();
    let nextId = Math.max(0, ...[...slide.getElementsByTagNameNS('*', 'cNvPr')].map(n => Number(n.getAttribute('id')) || 0)) + 1;
    for (const [part, layer, relationshipMap] of layers) {
      const layerTree = child(child(layer.documentElement, 'cSld'), 'spTree');
      const layerRels = readLayer(relPath(part),relationshipMap.get(relPath(part)));
      const mapping = new Map();
      layerMappings.set(layer, mapping);
      for (const rel of [...layerRels.documentElement.children]) {
        if (rel.getAttribute('TargetMode') === 'External') continue;
        const copy = slide.importNode(rel, true), id = `dsh-layer-${sequence++}`;
        mapping.set(rel.getAttribute('Id'), id); copy.setAttribute('Id', id);
        copy.setAttribute('Target', '/' + target(part, rel)); rels.documentElement.appendChild(rels.importNode(copy, true));
      }
      for (const node of [...(layerTree?.children ?? [])]) {
        if (!['sp','pic','grpSp','graphicFrame','cxnSp'].includes(node.localName)) continue;
        const copy = slide.importNode(node, true);
        if (!removePlaceholders(copy)) continue;
        for (const item of [copy, ...copy.getElementsByTagName('*')]) {
          if (item.localName === 'cNvPr') { item.setAttribute('id', String(nextId++)); item.setAttribute('name', `layer-${sequence++}-${item.getAttribute('name')}`); }
        }
        remapRelationships(copy,mapping);
        tree.insertBefore(copy, anchor ?? null);
      }
    }
    if (!child(common, 'bg')) {
      const bg = child(child(layout.documentElement, 'cSld'), 'bg') ?? child(child(master?.documentElement, 'cSld'), 'bg');
      if (bg) {
        const copy=slide.importNode(bg,true);
        let mapping=layerMappings.get(bg.ownerDocument);
        if (!mapping) {
          mapping=new Map();
          const part=bg.ownerDocument===layout?layoutPath:masterPath;
          const relationshipMap=bg.ownerDocument===layout?files.slideLayoutRels:files.slideMasterRels;
          const sourceRels=readLayer(relPath(part),relationshipMap.get(relPath(part)));
          for (const rel of [...sourceRels.documentElement.children]) {
            if (rel.getAttribute('TargetMode')==='External') continue;
            const id=`dsh-background-${sequence++}`,imported=rels.importNode(rel,true);
            mapping.set(rel.getAttribute('Id'),id);imported.setAttribute('Id',id);imported.setAttribute('Target','/'+target(part,rel));rels.documentElement.appendChild(imported);
          }
        }
        remapRelationships(copy,mapping);
        common.insertBefore(copy,tree);
      }
    }
    files.slides.set(slidePath, serializeOoXmlElement(slide.documentElement));
    files.slideRels.set(relKey, serializeOoXmlElement(rels.documentElement));
  }
}
