import { useLayoutEffect, useState } from 'react';
import { BookOpen } from 'lucide-react';
import { Button, Checkbox, Modal, SearchInput } from '@bisheng/ui';
import { useCategorizedKnowledgeSpaces, useLocalize } from '~/hooks';
import type { KnowledgeItem } from './knowledgeTypes';

interface KnowledgeSpaceDialogProps {
  value: KnowledgeItem[];
  onConfirm: (value: KnowledgeItem[]) => void;
  onClose: () => void;
}

const MAX_SPACES = 50;

/** Each opening owns a draft. Only confirmation changes the conversation context. */
export function KnowledgeSpaceDialog({ value, onConfirm, onClose }: KnowledgeSpaceDialogProps) {
  const localize = useLocalize();
  useLayoutEffect(() => {
    const presentation = window.dshChatPresentation;
    presentation?.reportKnowledgeDialog?.(true);
    return () => presentation?.reportKnowledgeDialog?.(false);
  }, []);
  const [draft, setDraft] = useState(() => value.filter((item) => item.type === 'space'));
  const [keyword, setKeyword] = useState('');
  const { groups, isFetching, isError, retry } = useCategorizedKnowledgeSpaces({ keyword });
  const selectedIds = new Set(draft.map((item) => String(item.id)));

  const handleToggle = (id: string, name: string) => {
    setDraft((current) => current.some((item) => String(item.id) === id)
      ? current.filter((item) => String(item.id) !== id)
      : current.length < MAX_SPACES ? [...current, { id, name, type: 'space' }] : current);
  };
  const handleConfirm = () => {
    // Organization knowledge remains independent of the selected spaces.
    onConfirm([...value.filter((item) => item.type !== 'space'), ...draft]);
    onClose();
  };

  return (
    <Modal open onOpenChange={(open) => { if (!open) onClose(); }}
      title={localize('dshChat.selectKnowledge')} closeLabel={localize('com_ui_close')}
      className="dsh-knowledge-dialog" overlayClassName="dsh-knowledge-overlay" bodyClassName="flex flex-col"
      footer={<>
        <span className="mr-auto self-center text-body-sm text-text-3" aria-live="polite">
          {localize('dshChat.selectedKnowledge', { count: draft.length })}
        </span>
        <Button color="default" variant="outlined" className="dsh-knowledge-cancel" onClick={onClose}>{localize('com_ui_cancel')}</Button>
        <Button onClick={handleConfirm} disabled={isError || isFetching}>
          {localize('dshChat.confirmKnowledge')}
        </Button>
      </>}
    >
      <SearchInput value={keyword} onChange={(event) => setKeyword(event.target.value)}
        placeholder={localize('dshChat.searchKnowledge')} aria-label={localize('dshChat.searchKnowledge')} />
      <div className="dsh-knowledge-columns">
        <span>{localize('dshChat.knowledgeColumn')}</span>
        <span>{localize('dshChat.modifiedColumn')}</span>
      </div>
      <div className="dsh-knowledge-list mt-4 min-h-[200px] overflow-y-auto" aria-busy={isFetching}>
        {isError ? (
          <div role="alert" className="flex flex-col items-center gap-3 py-10 text-text-3">
            <span>{localize('dshChat.knowledgeLoadError')}</span>
            <Button color="default" variant="outlined" onClick={() => void retry()}>{localize('dshChat.retryKnowledge')}</Button>
          </div>
        ) : isFetching && groups.length === 0 ? (
          <p role="status" className="py-10 text-center text-text-3">{localize('dshChat.loadingKnowledge')}</p>
        ) : groups.length === 0 ? (
          <p role="status" className="py-10 text-center text-text-3">{localize(keyword.trim() ? 'dshChat.noKnowledgeMatch' : 'dshChat.noKnowledge')}</p>
        ) : groups.map((group) => (
          <section key={group.key} className="mb-4">
            <h3 className="mb-2 text-body-sm text-text-3">{group.label}</h3>
            {group.spaces.filter((space) => space.id != null && String(space.id) !== '').map((space) => {
              const id = String(space.id);
              const checked = selectedIds.has(id);
              return (
                <label key={id} className="dsh-knowledge-row flex cursor-pointer items-center gap-3 rounded-lg px-2 py-3 hover:bg-fill-2" data-selected={checked}>
                  <Checkbox checked={checked} disabled={!checked && draft.length >= MAX_SPACES}
                    onCheckedChange={() => handleToggle(id, space.name)} aria-label={space.name} />
                  <span className="dsh-knowledge-icon"><BookOpen size={18} aria-hidden /></span>
                  <span className="min-w-0 flex-1 truncate text-body text-text-1" title={space.name}>{space.name}</span>
                  <time className="dsh-knowledge-modified" dateTime={space.updatedAt}>
                    {space.updatedAt && !Number.isNaN(Date.parse(space.updatedAt))
                      ? new Date(space.updatedAt).toLocaleDateString() : '—'}
                  </time>
                </label>
              );
            })}
          </section>
        ))}
      </div>
      {draft.length >= MAX_SPACES && <p role="status" className="text-body-sm text-text-3">{localize('dshChat.knowledgeLimit')}</p>}
    </Modal>
  );
}
