import { useTranslation } from 'react-i18next';
import type { ReferenceSlotState } from '@/types/assistant';

interface ReferenceStateHintProps {
    states?: ReferenceSlotState[] | null;
}
export function ReferenceStateHint({ states }: ReferenceStateHintProps) {
    const { t } = useTranslation();
    const invalid = states?.filter(row => !row.is_valid) ?? [];
    if (!invalid.length) return null;
    return <div role="status" className="text-xs text-text-3">
        <p>{t('references.partialRepair')}</p>
        {invalid.map(row => <p key={`${row.slot_key}:${row.target_type}:${row.target_id}`}>
            {row.target_id}: {t(`references.${row.state === 'valid' ? 'unavailable' : row.state}`)}
        </p>)}
    </div>;
}
