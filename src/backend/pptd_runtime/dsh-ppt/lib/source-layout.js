import { createHash } from 'node:crypto';

const canonical = value => Array.isArray(value) ? value.map(canonical) : value && typeof value === 'object'
  ? Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])])) : value;
function layoutDigest(element) {
  const { sourceLayout, ...content } = element;
  return createHash('sha256').update(JSON.stringify(canonical(content))).digest('hex');
}
/** Keep layout observations attached to unchanged source objects; edits return to authoring checks. */
export function markSourceLayout(element) { return { ...element, sourceLayout: layoutDigest(element) }; }
export function hasSourceLayout(element) {
  return typeof element.sourceLayout === 'string' && /^[a-f0-9]{64}$/.test(element.sourceLayout) && element.sourceLayout === layoutDigest(element);
}
