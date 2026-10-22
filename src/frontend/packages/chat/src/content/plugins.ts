import { asRecord } from '../core/normalizeHistory';
function walk(value: unknown, visitor: (node: Record<string, unknown>) => void) {
  const node = asRecord(value);
  visitor(node);
  if (Array.isArray(node.children)) node.children.forEach(child => walk(child, visitor));
}
export function remarkCitationPlugin() {
  return (tree: unknown) => walk(tree, node => {
    if (node.type !== 'text' || typeof node.value !== 'string' || !/\[citation:(\d+)\]|\[citationref:([^\]]+)\]/.test(node.value)) return;
    node.name = 'citation';
    node.data = { hName: 'citation', hProperties: node.attributes, ...asRecord(node.data) };
  });
}
export function artifactPlugin() {
  return (tree: unknown) => walk(tree, node => {
    if (!['textDirective', 'leafDirective', 'containerDirective'].includes(String(node.type)) || node.name !== 'artifact') return;
    node.data = { hName: 'artifact', hProperties: node.attributes, ...asRecord(node.data) };
  });
}
/** Only literal line breaks are upgraded; other generated HTML stays escaped. */
export function rehypeBr() {
  return (tree: unknown) => walk(tree, parent => {
    if (!Array.isArray(parent.children)) return;
    parent.children = parent.children.flatMap(value => {
      const node = asRecord(value);
      if (!['text', 'raw'].includes(String(node.type)) || typeof node.value !== 'string' || !/<br\s*\/?>/i.test(node.value)) return [value];
      return node.value.split(/<br\s*\/?>/gi).flatMap((segment, index, segments) => [
        ...(segment ? [{ type: 'text', value: segment }] : []),
        ...(index < segments.length - 1 ? [{ type: 'element', tagName: 'br', properties: {}, children: [] }] : []),
      ]);
    });
  });
}
