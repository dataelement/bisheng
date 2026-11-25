import { Button, Input, Modal } from '@bisheng/ui';
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { Link } from 'react-router-dom';
import { readWikiGraph, readWikiPage, readWikiStatus, searchWiki, type WikiPage, type WikiScope } from '~/api/knowledgeProviderWiki';
import { useAuthContext, useLocalize } from '~/hooks';
import { ProviderWikiGraph, wikiTypeLabel } from './ProviderWikiGraph';

// An unavailable capability route is not proof of Native: a preparing external binding has no active generation yet.
type WikiDiscovery = { tenant: string } | null;
interface EntryProps { spaceId: string; canRead: boolean; discovery: WikiDiscovery }
const fresh = { cacheTime: 0, retry: false, keepPreviousData: false } as const;
export function ProviderWikiEntry({ canRead, spaceId, discovery }: EntryProps) {
  const { user } = useAuthContext();
  if (!user?.id || !canRead || !discovery) return null;
  const identity = JSON.stringify([user.id, user.role, user.tenant_id, spaceId, discovery.tenant]);
  return <ScopedEntry key={identity} spaceId={spaceId} identity={identity} tenant={discovery.tenant} />;
}
interface ScopedEntryProps { spaceId: string; identity: string; tenant: string }
function ScopedEntry({ spaceId, identity, tenant }: ScopedEntryProps) {
  const localize = useLocalize();
  const [open, setOpen] = useState(false);
  const [revision, setRevision] = useState(0);
  const status = useQuery({ ...fresh, queryKey: ['wiki-status', identity, revision],
    queryFn: ({ signal }) => readWikiStatus(spaceId, tenant, signal),
    refetchInterval: open ? 15000 : false,
  });
  // The server checks visible + external binding before returning any status (including query_failed).
  if (!open && !status.isSuccess) return null;
  const proof = status.isSuccess ? status.data : undefined;
  const refresh = () => setRevision(n => n + 1);
  return <>
    <Button color="default" variant="outlined" disabled={!proof} onClick={() => { refresh(); setOpen(true); }}>{localize('com_knowledge.wiki.title')}</Button>
    {open && <Modal open onOpenChange={setOpen} size="large" title={localize('com_knowledge.wiki.title')} closeLabel={localize('com_ui_close')}
      footer={<Button color="default" variant="outlined" onClick={refresh}>{localize('com_knowledge.wiki.refresh')}</Button>}>
      {status.isLoading ? <p role="status">{localize('com_list_loading')}</p>
        : proof?.state === 'ready' ? <WikiBrowser key={JSON.stringify([proof.tenant, proof.generation, revision])}
          scope={{ spaceId, tenant: proof.tenant, generation: proof.generation }} identity={identity} revision={revision} />
        : <p role="status" className="py-6 text-body text-text-2">{localize(`com_knowledge.wiki.${proof?.state ?? 'unavailable'}`)}</p>}
    </Modal>}
  </>;
}
interface BrowserProps { scope: WikiScope; identity: string; revision: number }
function WikiBrowser({ scope, identity, revision }: BrowserProps) {
  const localize = useLocalize();
  const [draft, setDraft] = useState('');
  const [q, setQuery] = useState('');
  const [slug, setSlug] = useState('');
  const prefix = ['wiki-read', identity, scope.tenant, scope.spaceId, scope.generation, revision];
  const graph = useQuery({ ...fresh, queryKey: [...prefix, 'graph'], queryFn: ({ signal }) => readWikiGraph(scope, signal) });
  const hits = useQuery({ ...fresh, enabled: !!q, queryKey: [...prefix, 'search', q], queryFn: ({ signal }) => searchWiki(scope, q, signal) });
  const page = useQuery({ ...fresh, enabled: !!slug, queryKey: [...prefix, 'page', slug], queryFn: ({ signal }) => readWikiPage(scope, slug, signal) });
  if (graph.isError || hits.isError || page.isError) return <p role="status">{localize('com_knowledge.wiki.query_failed')}</p>;
  if (!graph.data) return <p role="status">{localize('com_list_loading')}</p>;
  return <div className="space-y-4 pb-4">
    <form className="flex items-center gap-2" onSubmit={event => { event.preventDefault(); setQuery(draft.trim()); }}>
      <Input type="search" value={draft} maxLength={512} aria-label={localize('com_knowledge.wiki.search')} placeholder={localize('com_knowledge.wiki.search')}
        onChange={event => { setDraft(event.target.value); setQuery(''); }} />
      <Button type="submit" color="default" variant="outlined" disabled={!draft.trim()}>{localize('com_knowledge.search')}</Button>
    </form>
    {q && (hits.isLoading ? <p role="status">{localize('com_list_loading')}</p> : hits.data?.length ? <ul className="max-h-36 overflow-auto">
      {hits.data.map(hit => <li key={hit.slug}><Button variant="text" onClick={() => setSlug(hit.slug)}>
        <span className="truncate">{hit.title} · {localize(wikiTypeLabel(hit.page_type))} · {hit.summary}</span>
      </Button></li>)}
    </ul> : <p role="status">{localize('com_knowledge.wiki.no_matches')}</p>)}
    {graph.data.nodes.length ? <ProviderWikiGraph graph={graph.data} selected={slug} onSelect={setSlug} /> : <p role="status">{localize('com_knowledge.wiki.empty')}</p>}
    {slug && (page.data ? <WikiDetail page={page.data} spaceId={scope.spaceId} titles={new Map(graph.data.nodes.map(n => [n.slug, n.title]))} onSelect={setSlug} />
      : <p role="status">{localize('com_list_loading')}</p>)}
  </div>;
}
interface DetailProps { page: WikiPage; spaceId: string; titles: Map<string, string>; onSelect: (slug: string) => void }
function WikiDetail({ page, spaceId, titles, onSelect }: DetailProps) {
  const localize = useLocalize();
  const related = [...new Set([...page.in_links, ...page.out_links])];
  return <article className="space-y-3 border-t border-border-base pt-4 text-body text-text-1">
    <span className="text-caption text-text-3">{localize(wikiTypeLabel(page.page_type))}</span>
    <h2 className="text-h3">{page.title}</h2><p className="text-text-2">{page.summary}</p>
    <ReactMarkdown className="prose max-w-none break-words" skipHtml disallowedElements={['img', 'a']} unwrapDisallowed>{page.content}</ReactMarkdown>
    {!!related.length && <section aria-label={localize('com_knowledge.wiki.related')}>
      <h3 className="text-h4">{localize('com_knowledge.wiki.related')}</h3>
      {related.map(s => <Button key={s} variant="link" onClick={() => onSelect(s)}>{titles.get(s) ?? s}</Button>)}
    </section>}
    {!!page.sources.length && <section><h3 className="text-h4">{localize('com_knowledge.wiki.sources')}</h3><ul>
      {page.sources.map((id, index) => <li key={index}>{id === null ? <span className="text-text-3">{localize('com_knowledge.wiki.restricted')}</span>
        : <Link className="text-blue-500" to={`/knowledge/file/${id}?spaceId=${encodeURIComponent(spaceId)}`}>{localize('com_knowledge.wiki.source_file', { id })}</Link>}</li>)}
    </ul></section>}
  </article>;
}
