import { unzipSync } from 'fflate';
import { JSDOM } from 'jsdom';
import { RECOMMENDED_ZIP_LIMITS as limits } from '@aiden0z/pptx-renderer';

const EMPTY_PREFIX_XMLNS = /\sxmlns:[A-Za-z_][\w.-]*\s*=\s*(?:""|'')/g;
const XML_MAP_KEYS = ['slides', 'slideRels', 'slideLayouts', 'slideLayoutRels', 'slideMasters', 'slideMasterRels', 'themes', 'themeOverrides', 'charts', 'chartRels', 'chartStyles', 'chartColors', 'diagramDrawings'];
const XML_STRING_KEYS = ['contentTypes', 'presentation', 'presentationRels', 'tableStyles'];

/** XML 1.0 forbids undeclaring a prefixed namespace; WPS/PowerPoint still emit xmlns:foo="". */
export function sanitizeOoXml(xml) {
  return String(xml ?? '').replace(EMPTY_PREFIX_XMLNS, '');
}

export function stripEmptyXmlnsDeclarations(node) {
  if (!node) return;
  if (node.attributes) {
    const names = [];
    for (const attr of node.attributes) {
      if (attr.value === '' && (attr.prefix === 'xmlns' || attr.name.startsWith('xmlns:'))) names.push(attr.name);
    }
    for (const name of names) node.removeAttribute(name);
  }
  for (const child of node.children ?? []) stripEmptyXmlnsDeclarations(child);
}

let xmlSerializerWindow;

function getXmlSerializer() {
  if (!xmlSerializerWindow) xmlSerializerWindow = new JSDOM('').window;
  return new xmlSerializerWindow.XMLSerializer();
}

/** Serialize OOXML without the well-formed outerHTML check that rejects empty prefix declarations. */
export function serializeOoXmlElement(node) {
  if (!node) return '';
  stripEmptyXmlnsDeclarations(node);
  return sanitizeOoXml(getXmlSerializer().serializeToString(node));
}

function sanitizeXmlMap(map) {
  if (!map) return;
  for (const [key, value] of map) {
    if (typeof value === 'string') map.set(key, sanitizeOoXml(value));
  }
}

export function sanitizePptxFiles(files) {
  if (!files) return files;
  for (const key of XML_STRING_KEYS) {
    if (typeof files[key] === 'string') files[key] = sanitizeOoXml(files[key]);
  }
  for (const key of XML_MAP_KEYS) sanitizeXmlMap(files[key]);
  return files;
}

/** OOXML relationships name resources; media and charts may live below the slide folder. */
export function supplementResources(files, bytes) {
  let total = 0;
  const extra = unzipSync(bytes, { filter(entry) {
    const name = entry.name.replaceAll('\\', '/');
    if (!name.startsWith('ppt/') || name.includes('..') || !/\/(?:media|charts)\/[^/]+\.(?:svg|png|jpe?g|gif|webp|emf|xml)$/i.test(name)) return false;
    if (files.media.has(name) || files.charts.has(name)) return false;
    total += entry.originalSize;
    if (entry.originalSize > limits.maxEntryUncompressedBytes || total > limits.maxTotalUncompressedBytes) throw new Error('PPTX 资源超过解析大小限制');
    return true;
  } });
  for (const [rawName, data] of Object.entries(extra)) {
    const name = rawName.replaceAll('\\', '/');
    const key = (() => { try { return decodeURIComponent(name); } catch { return name; } })();
    if (name.endsWith('.xml') && name.includes('/charts/')) { files.charts.set(name, Buffer.from(data).toString('utf8')); files.charts.set(key, files.charts.get(name)); }
    else { files.media.set(name, data); files.media.set(key, data); }
  }
  return files;
}

export function isSafeSvg(bytes) {
  const svg = Buffer.from(bytes).toString('utf8');
  if (/<!DOCTYPE|<!ENTITY/i.test(svg)) return false;
  const localReference = value => value.startsWith('#') || /^data:image\/(?:png|jpeg|gif|webp);base64,[a-z0-9+/=\s]+$/i.test(value);
  // Inspect decoded XML attributes, so entity-escaped links follow the same rule.
  let dom;
  try {
    dom = new JSDOM(svg, { contentType: 'image/svg+xml' });
    const root = dom.window.document.documentElement;
    if (root.localName !== 'svg' || root.namespaceURI !== 'http://www.w3.org/2000/svg') return false;
    return [root, ...root.querySelectorAll('*')].every(element => {
      if (/^(script|foreignObject|animate|animateMotion|animateTransform|set)$/i.test(element.localName)) return false;
      for (const attribute of element.attributes) {
        if (/^on/i.test(attribute.localName)) return false;
        if (/^(href|src)$/i.test(attribute.localName) && !localReference(attribute.value.trim())) return false;
      }
      const styles = (element.getAttribute('style') ?? '') + (element.localName === 'style' ? element.textContent : '') + [...element.attributes].map(a => a.value).join(' ');
      return !/@import|@font-face|\\/i.test(styles) && [...styles.matchAll(/url\(\s*["']?([^)'"\s]+)/gi)].every(match => localReference(match[1]));
    });
  } catch { return false; }
  finally { dom?.window.close(); }
}
