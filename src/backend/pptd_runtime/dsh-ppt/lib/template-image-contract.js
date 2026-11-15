import path from 'node:path';
import { unzipSync } from 'fflate';
import { JSDOM } from 'jsdom';
import { sanitizeOoXml } from './pptx-resources.js';

export const IMAGE_CONTRACT_SCHEMA = 'dsh.template-images/v1';
const MAX_BYTES = 64 * 1024;
const fail = message => { throw new Error(`模板配图规则：${message}`); };
const object = (v, keys) => {
  if (!v || typeof v !== 'object' || Array.isArray(v) || Object.keys(v).some(k => !keys.includes(k))) fail('字段应符合 v1 格式');
};
const text = v => { if (typeof v !== 'string' || !v.trim() || v.length > 500 || /[\x00-\x08\x0b\x0c\x0e-\x1f]/u.test(v)) fail('文字长度应为 1–500 字符'); };
const strings = v => { if (!Array.isArray(v) || v.length > 24) fail('列表最多 24 项'); v.forEach(text); };

/** Declarative visual data only. Tool selection, policy, credentials and execution belong to the Host. */
export function parseImageContract(notes, elements) {
  if (typeof notes !== 'string' || !notes.trim().startsWith('{')) return undefined;
  let c;
  try { c = JSON.parse(notes); } catch { if (notes.includes(IMAGE_CONTRACT_SCHEMA)) fail('JSON 格式无效'); return undefined; }
  if (c?.schema !== IMAGE_CONTRACT_SCHEMA) return undefined;
  if (Buffer.byteLength(notes) > MAX_BYTES) fail('单页规则超过 64 KB');
  object(c, ['schema', 'layoutId', 'pageRole', 'style', 'slots', 'contentPolicy']);
  if (c.contentPolicy !== undefined && c.contentPolicy !== 'provided-facts-or-qualitative') fail('内容来源策略无效');
  text(c.layoutId); text(c.pageRole);
  object(c.style, ['medium', 'palette', 'lighting', 'tone', 'textTreatment', 'continuity']);
  Object.values(c.style).forEach(text);
  if (Object.keys(c.style).length !== 6) fail('全局风格需要六项描述');
  if (!Array.isArray(c.slots) || c.slots.length > 16) fail('单页最多 16 个配图槽');
  const seen = new Set();
  for (const slot of c.slots) {
    object(slot, ['elementId', 'role', 'contentSources', 'sourcePolicy', 'subject', 'composition', 'aspectRatio', 'reuseGroup', 'maskElementIds']);
    for (const k of ['elementId', 'role', 'subject', 'composition', 'reuseGroup']) text(slot[k]);
    strings(slot.contentSources); strings(slot.maskElementIds);
    if (!['contextual-scene', 'provided-portrait', 'native-graphic'].includes(slot.sourcePolicy)) fail('素材来源策略无效');
    if (!['1:1', '16:9', '9:16', '4:3', '3:4'].includes(slot.aspectRatio)) fail('图片比例无效');
    if (seen.has(slot.elementId)) fail('图片槽重复');
    seen.add(slot.elementId);
    if (elements) {
      const requireType = (id, type) => { if (elements.find(e => e.elementId === id)?.elementType !== type) fail(`找不到 ${type} 槽 ${id}`); };
      requireType(slot.elementId, 'image');
      slot.contentSources.forEach(id => requireType(id, 'text'));
      slot.maskElementIds.forEach(id => requireType(id, 'shape'));
    }
  }
  return c;
}

/** Rebind object names during conversion, retaining the exact relation between content and image slots. */
export function remapImageContract(contract, names, elements) {
  if (!contract) return undefined;
  const result = structuredClone(contract);
  const resolve = (id, type) => { const ids = names.get(id); if (ids?.length !== 1) fail(`对象 ${id} 需要唯一匹配`); const candidates = elements.filter(e => [ids[0], `${ids[0]}-${type === 'text' ? 'text' : 'shape'}`].includes(e.elementId) && e.elementType === type); if (candidates.length !== 1) fail(`对象 ${id} 类型应为 ${type}`); return candidates[0].elementId; };
  for (const slot of result.slots) {
    slot.elementId = resolve(slot.elementId, 'image');
    slot.contentSources = slot.contentSources.map(id => resolve(id, 'text'));
    slot.maskElementIds = slot.maskElementIds.map(id => resolve(id, 'shape'));
  }
  const notes = JSON.stringify(result);
  parseImageContract(notes, elements);
  return notes;
}

/** Read only the relationship-selected notes body; bounded ZIP/XML processing performs no network access. */
export function readPptxImageContracts(bytes) {
  let total = 0;
  const parts = unzipSync(bytes, { filter(entry) {
    const name = entry.name.replaceAll('\\', '/');
    if (!/^ppt\/(?:slides\/_rels\/slide\d+\.xml\.rels|notesSlides\/notesSlide\d+\.xml)$/.test(entry.name)) return false;
    total += entry.originalSize;
    if (entry.originalSize > 256 * 1024 || total > 4 * 1024 * 1024) fail('备注数据超过大小限制');
    return true;
  } });
  const contracts = new Map();
  const xml = (data, visit) => {
    const source = sanitizeOoXml(Buffer.from(data).toString('utf8'));
    if (/<!DOCTYPE|<!ENTITY/i.test(source)) fail('备注 XML 应使用标准 OOXML');
    let dom;
    try { dom = new JSDOM(source, { contentType: 'application/xml' }); return visit(dom.window.document); }
    finally { dom?.window.close(); }
  };
  for (const [rawName, data] of Object.entries(parts)) {
    const name = rawName.replaceAll('\\', '/');
    if (!name.endsWith('.rels')) continue;
    const rels = xml(data, doc => [...doc.getElementsByTagNameNS('*', 'Relationship')].filter(r => r.getAttribute('Type')?.endsWith('/notesSlide')).map(r => ({ target: r.getAttribute('Target'), mode: r.getAttribute('TargetMode') })));
    if (rels.length > 1) fail('每页需要唯一备注关系');
    for (const rel of rels) {
      if (rel.mode === 'External' || !rel.target || rel.target.includes('\\')) continue;
      const target = path.posix.normalize(path.posix.join('ppt/slides', rel.target));
      if (!/^ppt\/notesSlides\/notesSlide\d+\.xml$/.test(target) || !parts[target]) continue;
      const notes = xml(parts[target], doc => [...doc.getElementsByTagNameNS('*', 'sp')].filter(sp => [...sp.getElementsByTagNameNS('*', 'ph')].some(ph => ph.getAttribute('type') === 'body')).map(sp => [...sp.getElementsByTagNameNS('*', 'p')].map(p => [...p.getElementsByTagNameNS('*', 't')].map(t => t.textContent).join('')).join('\n')).join('\n'));
      const contract = parseImageContract(notes);
      if (contract) contracts.set(`ppt/slides/${path.posix.basename(name, '.rels')}`, contract);
    }
  }
  return contracts;
}
