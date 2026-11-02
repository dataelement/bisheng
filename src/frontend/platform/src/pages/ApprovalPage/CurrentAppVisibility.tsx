import { Button } from '@bisheng/ui';
import { useTranslation } from 'react-i18next';
import type { AppCurrentVisibility } from '@/controllers/API/approval';
import { formatTimestamp } from '@/utils/displayTimestamp';

interface Props {
  value?: AppCurrentVisibility;
  onRefresh: () => void;
}

export function CurrentAppVisibility({ value, onRefresh }: Props) {
  const { t } = useTranslation('bs');
  const available = value?.state === 'available';
  return <section className="mt-3 space-y-2 text-body-sm text-text-1">
    <div className="flex items-center justify-between gap-2">
      <h4>{t('f115.visibility.title')}</h4>
      <Button size="small" variant="outline" onClick={onRefresh}>{t('f115.visibility.refresh')}</Button>
    </div>
    <p className="text-text-3">{t('f115.visibility.currentHint')}</p>
    {!available ? <p>{t(value?.state === 'deleted' ? 'f115.visibility.deleted' : 'f115.visibility.unavailable')}</p> : <>
      {value.owner_only === true && <p>{t('f115.visibility.ownerOnly')}</p>}
      {value.subjects.length === 0 && <p>{t('f115.visibility.noOrdinary')}</p>}
      <ul className="space-y-1">{value.subjects.map((entry, index) => <li key={`${entry.type}-${entry.id}-${entry.userset_relation}-${entry.include_children}-${index}`}>
        {t(`f115.visibility.${entry.type}`)} · {entry.name} ({entry.id})
        {entry.userset_relation && ` · ${t(`f115.visibility.${entry.userset_relation === 'subtree_member' ? 'member' : entry.userset_relation}`)}`}
        {entry.include_children && ` · ${t('f115.visibility.children')}`}
      </li>)}</ul>
    </>}
    {value?.admin_implicit_access && <p className="text-text-3">{t('f115.visibility.adminHint')}</p>}
    {value?.checked_at && <p className="text-text-3">{t('f115.visibility.checkedAt')} {formatTimestamp(value.checked_at)}</p>}
  </section>;
}
