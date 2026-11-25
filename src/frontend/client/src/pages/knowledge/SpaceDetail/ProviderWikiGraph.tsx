import { Button } from '@bisheng/ui';
import { useEffect, useMemo, useRef } from 'react';
import type { WikiGraph } from '~/api/knowledgeProviderWiki';
import { useLocalize } from '~/hooks';

const types = ['summary', 'entity', 'concept'];
export const wikiTypeLabel = (type: string) => `com_knowledge.wiki.${types.includes(type) ? type : 'page'}`;
interface Props { graph: WikiGraph; selected: string; onSelect: (slug: string) => void }

export function ProviderWikiGraph({ graph, selected, onSelect }: Props) {
  const localize = useLocalize();
  const selectedNode = useRef<HTMLButtonElement>(null);
  const layout = useMemo(() => {
    // Keep labels and hit targets readable as the graph grows. Columns group page types;
    // positions and edges use the same coordinate system inside a scrollable viewport.
    const order = [...new Set(graph.nodes.map(n => n.page_type))].sort((a, b) => types.indexOf(a) - types.indexOf(b));
    const counts = new Map<string, number>();
    const nodes = graph.nodes.map(node => {
      const row = counts.get(node.page_type) ?? 0;
      counts.set(node.page_type, row + 1);
      return { ...node, x: order.indexOf(node.page_type) * 184 + 88, y: row * 72 + 32 };
    });
    return { nodes, bySlug: new Map(nodes.map(n => [n.slug, n])), width: order.length * 184, height: Math.max(1, ...counts.values()) * 72 };
  }, [graph]);
  useEffect(() => { selectedNode.current?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' }); }, [selected]);
  return <div role="group" aria-label={localize('com_knowledge.wiki.graph')} className="max-h-72 overflow-auto rounded-lg border border-border-base bg-fill-1">
    <div className="relative" style={{ width: layout.width, height: layout.height }}>
      <svg aria-hidden="true" width={layout.width} height={layout.height} className="pointer-events-none absolute inset-0 text-text-3">
        {graph.edges.map((edge, i) => {
          const a = layout.bySlug.get(edge.source), b = layout.bySlug.get(edge.target);
          return a && b && <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="currentColor" />;
        })}
      </svg>
      {layout.nodes.map(n => <div key={n.slug} className="absolute w-36 -translate-x-1/2 -translate-y-1/2" style={{ left: n.x, top: n.y }}>
        <Button ref={selected === n.slug ? selectedNode : undefined} className="w-full" title={n.title} aria-pressed={selected === n.slug}
          color={selected === n.slug ? 'primary' : 'default'} variant={selected === n.slug ? 'filled' : 'outlined'} onClick={() => onSelect(n.slug)}>
          <span className="truncate">{n.title}</span>
        </Button>
      </div>)}
    </div>
  </div>;
}
