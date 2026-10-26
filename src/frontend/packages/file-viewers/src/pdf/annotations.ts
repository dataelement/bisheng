import { sanitizeHtml } from '../html/sanitizeHtml';
const tags = new Set(['div', 'p', 'span', 'b', 'i', 'strong', 'em', 'u', 's', 'br', 'ul', 'ol', 'li', 'sub', 'sup']);
const styles = new Set(['fontSize', 'fontFamily', 'fontWeight', 'fontStyle', 'color', 'lineHeight', 'textDecoration', 'verticalAlign', 'textAlign']);
function escape(value: unknown): string {
  return String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
/** PDF.js FreeText rich text is a restricted formatting tree, never active HTML. */
export function annotationHtml(value: unknown, depth = 0): string {
  if (!value || typeof value !== 'object' || depth > 40) return '';
  const node = value as Record<string, unknown>;
  const name = node.name === 'body' ? 'div' : String(node.name || '').toLowerCase();
  const children = Array.isArray(node.children) ? node.children.map(child => annotationHtml(child, depth + 1)).join('') : '';
  const text = typeof node.value === 'string' ? escape(node.value) : '';
  if (!tags.has(name)) return children + text;
  const attributes = node.attributes && typeof node.attributes === 'object' ? node.attributes as Record<string, unknown> : {};
  const style = attributes.style && typeof attributes.style === 'object' ? attributes.style as Record<string, unknown> : {};
  const css = Object.entries(style).filter(([key, item]) => styles.has(key) && (typeof item === 'string' || typeof item === 'number') && !/[;{}<>]|url\s*\(|expression\s*\(/i.test(String(item)))
    .map(([key, item]) => `${key.replace(/[A-Z]/g, match => `-${match.toLowerCase()}`)}:${String(item)}`).join(';');
  return sanitizeHtml(`<${name} style="${escape(css)}">${children}${text}</${name}>`);
}
