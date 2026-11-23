import { createHash } from 'node:crypto';
import yaml from 'js-yaml';
import { JSDOM } from 'jsdom';
import { markSourceLayout } from './source-layout.js';

export const PERSONAL_TEMPLATE_SAMPLE_VERSION = 1;
const DRAWING = 'http://schemas.openxmlformats.org/drawingml/2006/main';
const textOf = content => content.paragraphs?.length
  ? content.paragraphs.map(p => p.runs.map(r => r.text ?? '').join('')).join('\n')
  : String(content.text ?? '').replace(/<[^>]*>/gu, '');
const glyphs = text => [...text].reduce((n, c) => n + (/[^\u0000-\u02ff]/u.test(c) ? 1 : .55), 0);
const escape = text => text.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
const TITLES = {
  zh: { cover: '项目方案汇报', agenda: '目录', section: '章节标题', closing: '总结与展望', data: '数据与关键发现', visual: '图文内容展示', 'multi-block': '关键内容概览', content: '本页核心观点' },
  en: { cover: 'Project overview', agenda: 'Contents', section: 'Section overview', closing: 'Summary and outlook', data: 'Data and insights', visual: 'Visual overview', 'multi-block': 'Key priorities', content: 'Key insight' }
};
const BODY = {
  zh: ['概述业务背景，说明项目目标。', '梳理关键问题，明确行动方向。', '展示核心结论与下一步计划。'],
  en: ['Outline the context and goals.', 'Summarize the key priorities.', 'Describe the next steps.']
};
const AGENDA = { zh: ['项目背景', '主要内容', '实施计划', '总结展望'], en: ['Context', 'Key priorities', 'Plan', 'Summary'] };
const LABELS = ['关键内容', '主要观点', '行动计划'];

function pageRole(page, profile, index, count) {
  const words = page.elements.filter(e => e.elementType === 'text').map(e => textOf(e.content ?? {})).join('\n');
  if (index === 0) return 'cover';
  if (index === count - 1 && /谢谢|感谢|总结|展望|thank|summary|outlook/iu.test(words)) return 'closing';
  if (/^(?:目录|contents|agenda)\s*$/imu.test(words)) return 'agenda';
  const content = profile.slots.filter(s => s.kind === 'text' && s.role !== 'footer');
  if (content.length <= 2 && content.some(s => s.role === 'title' && s.fontSize >= 28)) return 'section';
  return profile.role;
}

function complexPage(page, profile) {
  const diagram = page.elements.filter(e => ['shape', 'line'].includes(e.elementType)).length;
  const labels = profile.slots.filter(s => s.kind === 'text' && s.role !== 'footer').length;
  // Keep charts, tables and dense diagram labels together with their original data.
  return profile.slots.some(s => ['chart', 'table'].includes(s.kind)) || (labels >= 8 && diagram >= 8);
}

function boundedExample(candidate, original, slot, language) {
  const budget = Math.min(glyphs(original), slot.textCapacity ?? Infinity);
  if (budget < (language === 'zh' ? 4 : 3)) return undefined;
  let value = '';
  for (const char of candidate) {
    if (glyphs(value + char) > budget) break;
    value += char;
  }
  if (value !== candidate) {
    if (language === 'en') value = value.replace(/\s+\S*$/u, '');
    else if (/[，。]/u.test(value)) value = value.slice(0, Math.max(value.lastIndexOf('，'), value.lastIndexOf('。')));
  }
  return value.trim() || undefined;
}

function distribute(value, runs) {
  const chars = [...value], total = runs.reduce((n, r) => n + glyphs(r.text ?? ''), 0);
  let used = 0, weight = 0;
  return runs.map((run, index) => {
    weight += glyphs(run.text ?? '');
    const end = index === runs.length - 1 ? chars.length : Math.max(used, Math.round(chars.length * weight / Math.max(1, total)));
    const text = chars.slice(used, end).join(''); used = end;
    return { ...run, text };
  });
}

function simplifyText(element, slot, role, ordinal, parser, serializer) {
  const content = element.content, original = textOf(content);
  if (!original.trim() || /^[\d\s.,/%+–—-]+$/u.test(original.trim())) return element;
  const document = content.nativeTextBody ? parser.parseFromString(content.nativeTextBody, 'application/xml') : undefined;
  if (document?.getElementsByTagName('parsererror').length) return element;
  const nativeParagraphs = document ? [...document.getElementsByTagNameNS(DRAWING, 'p')] : undefined;
  const paragraphs = content.paragraphs ?? [{ runs: [{ text: original, options: {} }] }];
  if (nativeParagraphs && nativeParagraphs.length !== paragraphs.length) return element;
  const headingIndex = paragraphs.findIndex(p => (p.runs ?? []).some(r => (r.text ?? '').trim()));
  let changed = false;
  const next = paragraphs.map((paragraph, index) => {
    const nodes = nativeParagraphs?.[index].getElementsByTagNameNS(DRAWING, 't');
    const runs = paragraph.runs ?? [];
    // Import materializes a bullet as a leading run; the native paragraph owns its glyph.
    const offset = nodes && runs.length === nodes.length + 1 && /^[✓•●▪◆\s]+$/u.test(runs[0].text) ? 1 : 0;
    const editable = runs.slice(offset);
    if (nodes && (nodes.length !== editable.length || [...nodes].some((n, i) => n.textContent !== editable[i].text))) return paragraph;
    const text = editable.map(r => r.text ?? '').join('');
    if (/^[\d\s.,/%+–—-]+$/u.test(text.trim())) return paragraph;
    const language=/[\u3400-\u9fff]/u.test(text)?'zh':'en';
    const heading=slot.role==='title' && index===headingIndex;
    const bodyIndex=slot.role==='title' ? Math.max(0,index-headingIndex-1) : index;
    const bodyOrdinal=ordinal+bodyIndex;
    const candidate=heading ? TITLES[language][role] : role==='agenda' ? AGENDA[language][bodyOrdinal%4]
      : language==='zh' && Math.min(glyphs(text),slot.textCapacity ?? Infinity)<=8 ? LABELS[bodyOrdinal%3] : BODY[language][bodyOrdinal%3];
    const sample = boundedExample(candidate, text, slot, language);
    if (!sample || sample === text) return paragraph;
    const replacement = distribute(sample, editable);
    if (nodes) replacement.forEach((run, i) => { nodes[i].textContent = run.text; });
    changed = true;
    return { ...paragraph, runs: [...runs.slice(0, offset), ...replacement] };
  });
  if (!changed) return element;
  const updated = { ...content, paragraphs: next, text: next.map(p => `<p>${escape(p.runs.map(r => r.text).join(''))}</p>`).join('') };
  if (document) updated.nativeTextBody = serializer.serializeToString(document.documentElement);
  // The bounded sample becomes the template's source layout. Subsequent user edits
  // change this digest and return to authored-content layout checks.
  return markSourceLayout({ ...element, content: updated });
}

function layoutKey(page, profile, role, width, height) {
  const quantize = (value, size) => Math.round(value / size * 50);
  const elements = page.elements.map(e => {
    const slot=profile.slots.find(s=>s.elementId===e.elementId);
    return {
      kind: e.elementType,
      bounds: e.bounds.map((n, i) => quantize(n, i % 2 ? height : width)),
      shape: e.nativeShape?.geometry ?? e.geometry ?? e.shapeName ?? e.shape ?? '',
      fill: e.fill, border: e.border, rotation: e.rotation,
      textStyle: e.elementType === 'text' ? {
        fontFace:slot?.fontFace,fontSize:Math.round((slot?.fontSize ?? 0)/2),color:slot?.color,bold:slot?.bold,
        paragraphs:e.content?.paragraphs?.map(p=>({...p,runs:(p.runs ?? []).map(r=>r.options)}))
      } : undefined
    };
  });
  return createHash('sha256').update(JSON.stringify({ role, background: page.background, elements })).digest('hex');
}

/** Normalize high-confidence text slots and select unique layouts, retaining every
 * source page in the authoring project and every asset in its source plane.
 * @param {import('./types/pptd.js').PptdProject} project
 * @param {import('./types/personal-template-profile.js').PersonalTemplateProfile} profile
 * @returns {{source: import('./types/pptd.js').PptdProjectSource, samples: import('./types/personal-template-samples.js').PersonalTemplateSamples}}
 */
export function createPersonalTemplateSamples(project, profile) {
  const window = new JSDOM('').window;
  try {
    const parser = new window.DOMParser(), serializer = new window.XMLSerializer();
    const pages = new Map(project.source.pages), seen = new Set(), layouts = [];
    let simplifiedTextCount = 0;
    project.pages.forEach((page, index) => {
      const pageProfile = profile.pages[index];
      const role = pageRole(page, pageProfile, index, project.pages.length);
      const preserve = complexPage(page, pageProfile);
      const data = yaml.load(pages.get(page.file), { schema: yaml.JSON_SCHEMA });
      const slots=new Map(pageProfile.slots.map(slot=>[slot.elementId,slot]));
      const bodyOrder=new Map(data.elements.filter(element=>{
        const slot=slots.get(element.elementId),text=textOf(element.content ?? {}).trim();
        return slot?.kind==='text' && slot.role==='body' && slot.action!=='review-branding' && text && !/^[\d\s.,/%+–—-]+$/u.test(text);
      }).sort((a,b)=>a.bounds[1]-b.bounds[1] || a.bounds[0]-b.bounds[0]).map((element,i)=>[element.elementId,i]));
      let changed = 0;
      if (!preserve) data.elements = data.elements.map(element => {
        const slot = slots.get(element.elementId);
        if (slot?.kind !== 'text' || slot.role === 'footer' || slot.action === 'review-branding') return element;
        const next = simplifyText(element, slot, role, bodyOrder.get(element.elementId) ?? 0, parser, serializer);
        if (next !== element) changed++;
        return next;
      });
      if (changed) pages.set(page.file, yaml.dump(data, { noRefs: true, lineWidth: -1 }));
      simplifiedTextCount += changed;
      // Complex preserved pages retain their own preview; their data can convey
      // distinct structures even when the enclosing boxes have identical bounds.
      const key = preserve ? page.file : layoutKey(page, pageProfile, role, project.width, project.height);
      const representative = !seen.has(key); seen.add(key);
      layouts.push({ slideNumber: index + 1, role, content: changed ? 'sample' : 'source', representative });
    });
    return { source: { ...project.source, pages }, samples: {
      version: PERSONAL_TEMPLATE_SAMPLE_VERSION, simplifiedTextCount, layouts,
      representativePages: layouts.filter(page => page.representative).map(page => page.slideNumber)
    } };
  } finally { window.close(); }
}

export function validPersonalTemplateSamples(samples, count) {
  return samples?.version === PERSONAL_TEMPLATE_SAMPLE_VERSION && Number.isInteger(samples.simplifiedTextCount) && samples.simplifiedTextCount >= 0
    && Array.isArray(samples.layouts) && samples.layouts.length === count
    && samples.layouts.every((page, i) => page?.slideNumber === i + 1 && ['cover', 'agenda', 'section', 'closing', 'content', 'multi-block', 'visual', 'data'].includes(page.role)
      && ['sample', 'source'].includes(page.content) && typeof page.representative === 'boolean')
    && Array.isArray(samples.representativePages) && samples.representativePages.length > 0
    && JSON.stringify(samples.representativePages) === JSON.stringify(samples.layouts.filter(page => page.representative).map(page => page.slideNumber));
}
