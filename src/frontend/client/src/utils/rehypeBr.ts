import { visit, SKIP } from 'unist-util-visit';

/**
 * Narrow rehype plugin: upgrade literal `<br>` / `<br/>` / `<br />` into real
 * line-break elements.
 *
 * The markdown pipeline intentionally does NOT enable raw-HTML parsing
 * (no rehype-raw) to avoid an XSS surface in AI / knowledge-base output, so
 * react-markdown keeps raw HTML as escaped text and `<br>` shows up verbatim —
 * most visibly inside table cells, which cannot contain real newlines.
 *
 * This plugin deliberately touches ONLY `<br>`: it splits any text/raw node on
 * the `<br>` pattern and inserts real break elements. Every other raw HTML tag
 * is left untouched (still rendered as safe text), so no new XSS surface opens.
 */
const BR_SPLIT = /<br\s*\/?>/gi;
const BR_TEST = /<br\s*\/?>/i;

// eslint-disable-next-line @typescript-eslint/no-explicit-any -- hast/unist nodes are loosely typed here
type AnyNode = any;

export function rehypeBr() {
  return (tree: AnyNode) => {
    visit(tree, (node: AnyNode, index: number | null, parent: AnyNode) => {
      if (parent == null || index == null) return;
      if (node.type !== 'text' && node.type !== 'raw') return;

      const value: unknown = node.value;
      if (typeof value !== 'string' || !BR_TEST.test(value)) return;

      const segments = value.split(BR_SPLIT);
      const replacement: AnyNode[] = [];
      segments.forEach((segment, i) => {
        if (segment) replacement.push({ type: 'text', value: segment });
        if (i < segments.length - 1) {
          replacement.push({ type: 'element', tagName: 'br', properties: {}, children: [] });
        }
      });

      parent.children.splice(index, 1, ...replacement);
      // Skip the nodes we just inserted so they are not re-visited.
      return [SKIP, index + replacement.length];
    });
  };
}
