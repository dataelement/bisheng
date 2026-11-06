import { useState } from 'react';
import { useCategorizedKnowledgeSpaces } from '~/hooks';
import { KnowledgePickerDialog, type KnowledgePickerSelectionProps } from './KnowledgePickerDialog';

/** Spaces retain their own grouped catalog and selection scope. */
export function KnowledgeSpaceDialog(props: KnowledgePickerSelectionProps) {
  const [keyword, setKeyword] = useState('');
  const { groups, isFetching, isError, retry } = useCategorizedKnowledgeSpaces({ keyword });
  return <KnowledgePickerDialog {...props} kind="space" keyword={keyword} onKeywordChange={setKeyword}
    groups={groups.map(group => ({ key: group.key, label: group.label, items: group.spaces }))}
    isFetching={isFetching} isError={isError} onRetry={() => { void retry(); }} />;
}
