import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Button } from '@bisheng/ui';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '~/components/ui';
import { useLocalize } from '~/hooks';
import { MAX_MANUAL_TAGS, readManualTags, readTagPage, saveManualTags, type ProviderTagRef } from '~/api/knowledgeProviderTags';
import type { TagScope } from '../hooks/useSpaceCapabilities';
import { TAG_PAGE_SIZE, TagPagination } from './TagPagination';

interface ProviderTagEditorProps {
  spaceId: string; fileId: string; scope: Extract<TagScope, { kind: 'provider' }>;
  canEdit: boolean; onClose: (clean: boolean) => void; onSaved?: () => void;
}
export function ProviderTagEditor({ spaceId, fileId, scope, canEdit, onClose, onSaved }: ProviderTagEditorProps) {
  const localize = useLocalize();
  const [page, setPage] = useState(1);
  const [attempt, setAttempt] = useState(0);
  const [draft, setDraft] = useState<{ refs: Set<ProviderTagRef>; revision: number } | null>(null);
  const [clearing, setClearing] = useState(false);
  const [issue, setIssue] = useState<'conflict' | 'unconfirmed' | null>(null);
  const [saving, setSaving] = useState(false);
  const busy = useRef(false);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const target = { spaceId, tenant: scope.tenant, generation: scope.generation };
  const base = ['provider-tag-editor', scope.key, fileId, attempt];
  // Freeze the read revision for this draft. A background refresh cannot rebase the write.
  const opts = { cacheTime: 0, staleTime: Infinity, retry: false, refetchOnMount: false, refetchOnWindowFocus: false, refetchOnReconnect: false };
  const selection = useQuery({ ...opts, queryKey: [...base, 'selection'], queryFn: ({ signal }) => readManualTags(target, fileId, signal) });
  const catalog = useQuery({ ...opts, queryKey: [...base, 'page', page], queryFn: ({ signal }) => readTagPage(target, page, TAG_PAGE_SIZE, signal) });
  const selected = draft?.refs ?? new Set(selection.data?.tag_ref_ids);
  const writable = canEdit && scope.editable && selection.isSuccess && catalog.isSuccess && !issue && !saving;
  const changed = !!draft && (draft.refs.size !== selection.data?.tag_ref_ids.length || selection.data.tag_ref_ids.some(id => !draft.refs.has(id)));
  const handleReload = () => { setDraft(null); setClearing(false); setIssue(null); setPage(1); setAttempt(n => n + 1); };
  const handleToggle = (id: ProviderTagRef) => {
    if (!writable || !selection.data || (!selected.has(id) && selected.size >= MAX_MANUAL_TAGS)) return;
    const next = new Set(selected); if (!next.delete(id)) next.add(id);
    setDraft({ refs: next, revision: draft?.revision ?? selection.data.revision }); setClearing(false);
  };
  const maySubmit = writable && changed && (selected.size > 0 || clearing);
  const handleSave = async () => {
    if (!maySubmit || busy.current || !draft) return;
    busy.current = true; setSaving(true);
    try {
      await saveManualTags(target, fileId, draft.revision, clearing ? 'clear' : 'replace', [...selected]);
      if (mounted.current) { onSaved?.(); onClose(true); }
    } catch (error) {
      if (mounted.current) setIssue((error as { status_code?: number } | null)?.status_code === 10998 ? 'conflict' : 'unconfirmed');
    } finally { busy.current = false; if (mounted.current) setSaving(false); }
  };
  const handleClose = () => { if (!busy.current) onClose(!changed); };
  return <Dialog open onOpenChange={v => !v && handleClose()}><DialogContent className="max-h-[85dvh] overflow-y-auto">
    <DialogHeader><DialogTitle>{localize('com_knowledge.edit_tags')}</DialogTitle></DialogHeader>
    {issue && <div role="alert">{localize(`com_knowledge.provider_tags.${issue}`)}</div>}
    {(selection.isError || catalog.isError) && <p role="alert">{localize('com_knowledge.provider_tags.load_failed')}</p>}
    {(selection.isError || catalog.isError || issue) && <Button variant="text" onClick={handleReload}>{localize('com_knowledge.provider_tags.reload')}</Button>}
    {(!canEdit || !scope.editable) && <p role="status">{localize('com_knowledge.provider_tags.read_only')}</p>}
    {(catalog.isLoading || selection.isLoading) && <p role="status">{localize('com_ui_loading')}</p>}
    {selection.isSuccess && <p>{localize('com_knowledge.provider_tags.selected', { count: selected.size, max: MAX_MANUAL_TAGS })}</p>}
    {catalog.data && <>
      <div className="flex flex-wrap gap-1">{catalog.data.data.map(word => <Button key={word.tag_ref_id} size="small"
        variant={selected.has(word.tag_ref_id) ? 'secondary' : 'outline'} aria-pressed={selected.has(word.tag_ref_id)}
        disabled={!writable || (!selected.has(word.tag_ref_id) && selected.size >= MAX_MANUAL_TAGS)} onClick={() => handleToggle(word.tag_ref_id)}>{word.name}</Button>)}</div>
      {catalog.data.total === 0 && <p>{localize('com_knowledge.no_tags')}</p>}
      <TagPagination page={page} total={catalog.data.total} onChange={setPage} />
    </>}
    {canEdit && scope.editable && <Button variant="text" disabled={!writable || !selection.data?.tag_ref_ids.length || clearing}
      onClick={() => { if (selection.data) { setDraft({ refs: new Set(), revision: draft?.revision ?? selection.data.revision }); setClearing(true); } }}>{localize('com_knowledge.provider_tags.clear')}</Button>}
    <DialogFooter><Button variant="outline" disabled={saving} onClick={handleClose}>{localize('com_knowledge.cancel')}</Button>
      <Button disabled={!maySubmit} loading={saving} onClick={handleSave}>{localize('com_knowledge.confirm')}</Button></DialogFooter>
  </DialogContent></Dialog>;
}
