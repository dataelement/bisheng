import { useSelectLabels } from '@/components/bs-comp/formFields/useSelectLabels';
import { Select, type SelectOption } from '@bisheng/ui';
import { useKnowledgeCandidates } from './useKnowledgeCandidates';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

interface QaKnowledgeSelectProps {
    value: SelectOption[];
    error?: boolean;
    multiple?: boolean;
    className?: string;
    label?: string;
    onChange: (options: SelectOption[]) => void;
}

export function QaKnowledgeSelect({ value, error = false, multiple = true, className, label, onChange }: QaKnowledgeSelectProps) {
    const { t } = useTranslation();
    const selectLabels = useSelectLabels();
    const [open, setOpen] = useState(false);
    const candidates = useKnowledgeCandidates('qa', open);
    const saved = new Map(value.map(item => [String(item.value), item]));
    const fetched = candidates.options.map(item => ({ ...item, value: saved.get(String(item.value))?.value ?? item.value }));
    const known = new Set(fetched.map(item => String(item.value)));
    const options = [...fetched, ...value.filter(item => !known.has(String(item.value))).map(item => ({ ...item, disabled: true }))];

    const sharedProps = {
        ...selectLabels,
        id: 'knowledgeLib',
        'aria-label': label || t('dataset.selectQaKnowledgeLib'),
        className,
        showSearch: true,
        status: error ? 'error' as const : 'default' as const,
        options,
        placeholder: t('build.selectKnowledgeBase'),
        open,
        onOpenChange: (next: boolean) => {
            setOpen(next);
            if (!next) candidates.search('');
        },
        onSearch: candidates.search,
        onLoadMore: candidates.loadMore,
        loading: candidates.loading,
        loadingMore: candidates.loadingMore,
    };

    return multiple
        ? <Select {...sharedProps} multiple value={value.map(option => option.value)}
            onChange={(ids) => onChange(ids.map(id => saved.get(String(id)) ?? fetched.find(item => String(item.value) === String(id))!))} />
        : <Select {...sharedProps} value={value[0]?.value ?? null}
            onChange={(_value, option) => onChange(option ? [option] : [])} />;
}
