import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useLocalize } from '~/hooks';
import { readProviderTagLabels } from '~/api/knowledgeProviderTags';
import type { TagScope } from '../hooks/useSpaceCapabilities';
import TagGroup from './TagGroup';

interface ProviderFileTagsProps {
  spaceId: string;
  fileId: string;
  scope: Extract<TagScope, { kind: 'provider' }>;
  variant?: 'text' | 'text-h5' | 'text-list';
}

/**
 * Per-row tags for an external space, loaded only when the user asks for them.
 *
 * A provider listing carries no tags and the upstream has no batch tag read, so
 * resolving a whole page would cost one slow remote call per row. One click is one
 * read of one document; the result stays cached for the rest of the visit.
 */
export function ProviderFileTags({ spaceId, fileId, scope, variant = 'text-list' }: ProviderFileTagsProps) {
  const localize = useLocalize();
  const [requested, setRequested] = useState(false);
  const target = { spaceId, tenant: scope.tenant, generation: scope.generation };
  const query = useQuery({
    queryKey: ['provider-file-tags', scope.key, fileId],
    queryFn: ({ signal }) => readProviderTagLabels(target, fileId, signal),
    enabled: requested,
    retry: false,
    cacheTime: 5 * 60 * 1000,
    staleTime: 60 * 1000,
  });
  const stop = (event: React.MouseEvent) => event.stopPropagation();

  if (!requested) {
    return (
      <button
        type="button"
        className="shrink-0 whitespace-nowrap text-[10px] leading-[18px] text-text-3 hover:text-text-2"
        onClick={(event) => {
          stop(event);
          setRequested(true);
        }}
        onPointerDown={stop}
      >
        {localize('com_knowledge.provider_tags.show_names')}
      </button>
    );
  }
  if (query.isLoading) {
    return <span className="shrink-0 text-[10px] leading-[18px] text-text-3">{localize('com_ui_loading')}</span>;
  }
  if (query.isError) {
    return (
      <span className="shrink-0 text-[10px] leading-[18px] text-text-3">
        {localize('com_knowledge.provider_tags.names_unavailable')}
      </span>
    );
  }
  const names = query.data ?? [];
  if (names.length === 0) {
    return <span className="shrink-0 text-[10px] leading-[18px] text-text-3">{localize('com_knowledge.provider_tags.none')}</span>;
  }
  // Names are display-only: the numeric id here is a render key, never a tag reference.
  return <TagGroup tags={names.map((name, index) => ({ id: index + 1, name }))} variant={variant} />;
}
