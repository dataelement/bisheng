import { useLayoutEffect, useState } from 'react';
import { BookOpen } from 'lucide-react';
import { Button, Checkbox, Modal, SearchInput } from '@bisheng/ui';
import { useLocalize } from '~/hooks';
import type { KnowledgeItem, KnowledgeType } from './knowledgeTypes';

export interface KnowledgePickerGroup {
  key: string;
  label?: string;
  items: Array<{ id: string | number; name: string; updatedAt?: string | null }>;
}

export interface KnowledgePickerSelectionProps {
  value: KnowledgeItem[];
  onConfirm: (value: KnowledgeItem[]) => void;
  onClose: () => void;
}

interface KnowledgePickerDialogProps extends KnowledgePickerSelectionProps {
  kind: KnowledgeType;
  keyword: string;
  onKeywordChange: (keyword: string) => void;
  groups: KnowledgePickerGroup[];
  isFetching: boolean;
  isError: boolean;
  onRetry: () => void;
  hasMore?: boolean;
  onLoadMore?: () => void;
}

const MAX_SELECTED = 50;

/** Both knowledge pickers keep a draft until confirmation, including across searches. */
export function KnowledgePickerDialog({ kind, value, onConfirm, onClose, keyword, onKeywordChange,
  groups, isFetching, isError, onRetry, hasMore, onLoadMore }: KnowledgePickerDialogProps) {
  const localize = useLocalize();
  useLayoutEffect(() => {
    const presentation = window.dshChatPresentation;
    presentation?.reportKnowledgeDialog?.(true);
    return () => presentation?.reportKnowledgeDialog?.(false);
  }, []);
  const [draft, setDraft] = useState(() => value.filter(item => item.type === kind));
  const selectedIds = new Set(draft.map(item => String(item.id)));
  const copy = kind === 'org' ? {
    title: 'dshChat.selectKnowledgeBases', search: 'knowledgeBasePicker.search',
    column: 'knowledgeBasePicker.column', selected: 'knowledgeBasePicker.selected',
    loadError: 'knowledgeBasePicker.loadError', loading: 'knowledgeBasePicker.loading',
    noMatch: 'knowledgeBasePicker.noMatch', empty: 'knowledgeBasePicker.empty', limit: 'knowledgeBasePicker.limit',
  } as const : {
    title: 'dshChat.selectKnowledge', search: 'dshChat.searchKnowledge',
    column: 'dshChat.knowledgeColumn', selected: 'dshChat.selectedKnowledge',
    loadError: 'dshChat.knowledgeLoadError', loading: 'dshChat.loadingKnowledge',
    noMatch: 'dshChat.noKnowledgeMatch', empty: 'dshChat.noKnowledge', limit: 'dshChat.knowledgeLimit',
  } as const;

  const handleToggle = (id: string, name: string) => {
    setDraft(current => current.some(item => String(item.id) === id)
      ? current.filter(item => String(item.id) !== id)
      : current.length < MAX_SELECTED ? [...current, { id, name, type: kind }] : current);
  };
  const handleConfirm = () => {
    onConfirm([...value.filter(item => item.type !== kind), ...draft]);
    onClose();
  };

  return <Modal open onOpenChange={open => { if (!open) onClose(); }}
    title={localize(copy.title)} closeLabel={localize('com_ui_close')}
    className="dsh-knowledge-dialog" overlayClassName="dsh-knowledge-overlay" bodyClassName="flex flex-col"
    footer={<>
      <span className="mr-auto self-center text-body-sm text-text-3" aria-live="polite">
        {localize(copy.selected, { count: draft.length })}
      </span>
      <Button color="default" variant="outlined" className="dsh-knowledge-cancel" onClick={onClose}>{localize('com_ui_cancel')}</Button>
      <Button onClick={handleConfirm} disabled={isError || isFetching}>{localize('dshChat.confirmKnowledge')}</Button>
    </>}
  >
    <SearchInput value={keyword} onChange={event => onKeywordChange(event.target.value)}
      placeholder={localize(copy.search)} aria-label={localize(copy.search)} />
    <div className="dsh-knowledge-columns">
      <span>{localize(copy.column)}</span><span>{localize('dshChat.modifiedColumn')}</span>
    </div>
    <div className="dsh-knowledge-list mt-4 min-h-[200px] overflow-y-auto" aria-busy={isFetching}
      onScroll={event => {
        const { scrollHeight, scrollTop, clientHeight } = event.currentTarget;
        if (hasMore && !isFetching && scrollHeight - scrollTop <= clientHeight + 16) onLoadMore?.();
      }}>
      {isError ? <div role="alert" className="flex flex-col items-center gap-3 py-10 text-text-3">
        <span>{localize(copy.loadError)}</span>
        <Button color="default" variant="outlined" onClick={onRetry}>{localize('dshChat.retryKnowledge')}</Button>
      </div> : isFetching && groups.length === 0 ? (
        <p role="status" className="py-10 text-center text-text-3">{localize(copy.loading)}</p>
      ) : groups.length === 0 ? (
        <p role="status" className="py-10 text-center text-text-3">{localize(keyword.trim() ? copy.noMatch : copy.empty)}</p>
      ) : groups.map(group => <section key={group.key} className="mb-4">
        {group.label && <h3 className="mb-2 text-body-sm text-text-3">{group.label}</h3>}
        {group.items.filter(item => item.id != null && String(item.id) !== '').map(item => {
          const id = String(item.id);
          const checked = selectedIds.has(id);
          return <label key={id} className="dsh-knowledge-row flex cursor-pointer items-center gap-3 rounded-lg px-2 py-3 hover:bg-fill-2" data-selected={checked}>
            <Checkbox checked={checked} disabled={!checked && draft.length >= MAX_SELECTED}
              onCheckedChange={() => handleToggle(id, item.name)} aria-label={item.name} />
            <span className="dsh-knowledge-icon"><BookOpen size={18} aria-hidden /></span>
            <span className="min-w-0 flex-1 truncate text-body text-text-1" title={item.name}>{item.name}</span>
            <time className="dsh-knowledge-modified" dateTime={item.updatedAt ?? undefined}>
              {item.updatedAt && !Number.isNaN(Date.parse(item.updatedAt)) ? new Date(item.updatedAt).toLocaleDateString() : '—'}
            </time>
          </label>;
        })}
      </section>)}
      {isFetching && groups.length > 0 && <p role="status" className="py-3 text-center text-text-3">{localize(copy.loading)}</p>}
    </div>
    {draft.length >= MAX_SELECTED && <p role="status" className="text-body-sm text-text-3">{localize(copy.limit)}</p>}
  </Modal>;
}
