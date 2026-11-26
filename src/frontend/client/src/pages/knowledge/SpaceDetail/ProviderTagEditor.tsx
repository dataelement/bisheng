import { useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@bisheng/ui';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, Input } from '~/components/ui';
import { useLocalize } from '~/hooks';
import {
  createProviderTag,
  MAX_MANUAL_TAGS,
  MAX_TAG_NAME_LENGTH,
  readManualTags,
  readTagPage,
  saveManualTags,
  type ProviderTagRef,
} from '~/api/knowledgeProviderTags';
import type { TagScope } from '../hooks/useSpaceCapabilities';
import { TAG_PAGE_SIZE, TagPagination } from './TagPagination';

interface ProviderTagEditorProps {
  spaceId: string; fileId: string; scope: Extract<TagScope, { kind: 'provider' }>;
  canEdit: boolean;
  /** Space tag management (`knowledge_space` edit): required to add a word to the vocabulary. */
  canCreate?: boolean;
  onClose: (clean: boolean) => void; onSaved?: () => void;
}
type EditIssue = 'conflict' | 'unconfirmed' | 'create_failed' | 'rejected';

/** Definite refusals prove nothing was written; only transport failures are unknown. */
const REJECTED_CODES = new Set([400, 401, 403, 404, 405, 409, 422, 18089]);

function issueOf(error: unknown, fallback: EditIssue): EditIssue {
  const code = (error as { status_code?: number } | null)?.status_code;
  if (code === 10998) return 'conflict';
  return typeof code === 'number' && REJECTED_CODES.has(code) ? 'rejected' : fallback;
}
export function ProviderTagEditor({ spaceId, fileId, scope, canEdit, canCreate = false, onClose, onSaved }: ProviderTagEditorProps) {
  const localize = useLocalize();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [attempt, setAttempt] = useState(0);
  const [draft, setDraft] = useState<{ refs: Set<ProviderTagRef>; revision: number } | null>(null);
  const [clearing, setClearing] = useState(false);
  const [issue, setIssue] = useState<EditIssue | null>(null);
  const [saving, setSaving] = useState(false);
  const [creating, setCreating] = useState(false);
  // Words created in this dialog may not sit on a fetched page yet, so render them locally.
  const [createdWords, setCreatedWords] = useState<{ tag_ref_id: ProviderTagRef; name: string }[]>([]);
  const [newName, setNewName] = useState('');
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
  const writable = canEdit && scope.editable && selection.isSuccess && catalog.isSuccess && !issue && !saving && !creating;
  const changed = !!draft && (draft.refs.size !== selection.data?.tag_ref_ids.length || selection.data.tag_ref_ids.some(id => !draft.refs.has(id)));
  const canWriteWord = canCreate && scope.editable && selection.isSuccess && !issue && !saving && !creating;
  const handleReload = () => { setDraft(null); setClearing(false); setIssue(null); setPage(1); setAttempt(n => n + 1); };
  const handleToggle = (id: ProviderTagRef) => {
    if (!writable || !selection.data || (!selected.has(id) && selected.size >= MAX_MANUAL_TAGS)) return;
    const next = new Set(selected); if (!next.delete(id)) next.add(id);
    setDraft({ refs: next, revision: draft?.revision ?? selection.data.revision }); setClearing(false);
  };
  // A new word is a space-level action: it lands in the vocabulary right away and
  // is attached to this file only when the dialog is confirmed.
  const handleCreate = async () => {
    const name = newName.trim();
    if (!canWriteWord || !name || !selection.data || selected.size >= MAX_MANUAL_TAGS) return;
    setCreating(true); setIssue(null);
    try {
      const word = await createProviderTag(target, name);
      if (!mounted.current) return;
      setCreatedWords(old => old.some(w => w.tag_ref_id === word.tag_ref_id) ? old : [...old, { tag_ref_id: word.tag_ref_id, name: word.name }]);
      setDraft({ refs: new Set([...selected, word.tag_ref_id]), revision: draft?.revision ?? selection.data.revision });
      setClearing(false);
      setNewName('');
      // The vocabulary revision moved; re-read pages only, never the frozen selection.
      void queryClient.invalidateQueries({ queryKey: [...base, 'page'] });
    } catch (error) {
      if (mounted.current) setIssue(issueOf(error, 'create_failed'));
    } finally {
      if (mounted.current) setCreating(false);
    }
  };
  const maySubmit = writable && changed && (selected.size > 0 || clearing);
  // The whole-set fallback has no upstream revision: saving rewrites the document's
  // complete tag list, so the user must know that the selection is the final state.
  const wholeSet = selection.data?.edit_contract === 'whole-tags-v1';
  const handleSave = async () => {
    if (!maySubmit || busy.current || !draft) return;
    busy.current = true; setSaving(true);
    try {
      await saveManualTags(target, fileId, draft.revision, clearing ? 'clear' : 'replace', [...selected]);
      if (mounted.current) { onSaved?.(); onClose(true); }
    } catch (error) {
      // A refusal is not an unknown outcome: telling the user "could not confirm"
      // sends them to retry a write the server already rejected.
      if (mounted.current) setIssue(issueOf(error, 'unconfirmed'));
    } finally { busy.current = false; if (mounted.current) setSaving(false); }
  };
  const handleClose = () => { if (!busy.current) onClose(!changed); };
  const listed = (id: ProviderTagRef) => !!catalog.data?.data.some(word => word.tag_ref_id === id);
  return <Dialog open onOpenChange={v => !v && handleClose()}><DialogContent className="max-h-[85dvh] overflow-y-auto">
    <DialogHeader><DialogTitle>{localize('com_knowledge.edit_tags')}</DialogTitle></DialogHeader>
    {issue && <div role="alert">{localize(`com_knowledge.provider_tags.${issue}`)}</div>}
    {(selection.isError || catalog.isError) && <p role="alert">{localize('com_knowledge.provider_tags.load_failed')}</p>}
    {(selection.isError || catalog.isError || issue) && <Button variant="text" onClick={handleReload}>{localize('com_knowledge.provider_tags.reload')}</Button>}
    {(!canEdit || !scope.editable) && <p role="status">{localize('com_knowledge.provider_tags.read_only')}</p>}
    {wholeSet && <p role="status">{localize('com_knowledge.provider_tags.whole_set_warning')}</p>}
    {canEdit && scope.editable && !canCreate && <p role="status">{localize('com_knowledge.provider_tags.word_create_denied')}</p>}
    {(catalog.isLoading || selection.isLoading) && <p role="status">{localize('com_ui_loading')}</p>}
    {selection.isSuccess && <p>{localize('com_knowledge.provider_tags.selected', { count: selected.size, max: MAX_MANUAL_TAGS })}</p>}
    {canWriteWord && <div className="flex items-center gap-2">
      <Input value={newName} maxLength={MAX_TAG_NAME_LENGTH} disabled={creating}
        placeholder={localize('com_knowledge.provider_tags.new_word_placeholder')}
        onChange={event => setNewName(event.target.value)}
        onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); void handleCreate(); } }} />
      <Button variant="outline" size="small" loading={creating}
        disabled={!newName.trim() || selected.size >= MAX_MANUAL_TAGS || creating}
        onClick={() => void handleCreate()}>{localize('com_knowledge.provider_tags.new_word')}</Button>
    </div>}
    {catalog.data && <>
      <div className="flex flex-wrap gap-1">{catalog.data.data.map(word => <Button key={word.tag_ref_id} size="small"
        variant={selected.has(word.tag_ref_id) ? 'secondary' : 'outline'} aria-pressed={selected.has(word.tag_ref_id)}
        disabled={!writable || (!selected.has(word.tag_ref_id) && selected.size >= MAX_MANUAL_TAGS)} onClick={() => handleToggle(word.tag_ref_id)}>{word.name}</Button>)}</div>
      {catalog.data.total === 0 && <p>{localize('com_knowledge.no_tags')}</p>}
      <TagPagination page={page} total={catalog.data.total} onChange={setPage} />
    </>}
    {createdWords.filter(word => !listed(word.tag_ref_id)).map(word => <Button key={word.tag_ref_id} size="small"
      variant={selected.has(word.tag_ref_id) ? 'secondary' : 'outline'} aria-pressed={selected.has(word.tag_ref_id)}
      disabled={!writable} onClick={() => handleToggle(word.tag_ref_id)}>{word.name}</Button>)}
    {canEdit && scope.editable && <Button variant="text" disabled={!writable || !selection.data?.tag_ref_ids.length || clearing}
      onClick={() => { if (selection.data) { setDraft({ refs: new Set(), revision: draft?.revision ?? selection.data.revision }); setClearing(true); } }}>{localize('com_knowledge.provider_tags.clear')}</Button>}
    <DialogFooter><Button variant="outline" disabled={saving} onClick={handleClose}>{localize('com_knowledge.cancel')}</Button>
      <Button disabled={!maySubmit || creating} loading={saving} onClick={handleSave}>{localize('com_knowledge.confirm')}</Button></DialogFooter>
  </DialogContent></Dialog>;
}
