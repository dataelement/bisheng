import { Button } from '@bisheng/ui';
import type { AppCurrentVisibility } from '~/api/approval';
import { formatTime, type LocalizeFn } from './approvalPresentation';

interface Props {
  value?: AppCurrentVisibility;
  localize: LocalizeFn;
  onRefresh?: () => void;
}

export function CurrentAppVisibility({ value, localize, onRefresh }: Props) {
  const available = value?.state === 'available';
  return <section className="space-y-2 text-body-sm text-text-1">
    <div className="flex items-center justify-between gap-2">
      <h4>{localize('com_approval_app_publish_section_visibility')}</h4>
      {onRefresh && <Button size="small" variant="outlined" onClick={onRefresh}>{localize('approval.current_visibility.refresh')}</Button>}
    </div>
    <p className="text-text-3">{localize('approval.current_visibility.currentHint')}</p>
    {!available ? <p>{localize(value?.state === 'deleted' ? 'approval.current_visibility.deleted' : 'approval.current_visibility.unavailable')}</p> : <>
      {value.owner_only === true && <p>{localize('approval.current_visibility.ownerOnly')}</p>}
      {value.subjects.length === 0 && <p>{localize('approval.current_visibility.noOrdinary')}</p>}
      <ul className="space-y-1">{value.subjects.map((entry, index) => <li key={`${entry.type}-${entry.id}-${entry.userset_relation}-${entry.include_children}-${index}`}>
        {localize(`approval.current_visibility.${entry.type}`)} · {entry.name} ({entry.id})
        {entry.userset_relation && ` · ${localize(`approval.current_visibility.${entry.userset_relation === 'subtree_member' ? 'member' : entry.userset_relation}`)}`}
        {entry.include_children && ` · ${localize('approval.current_visibility.children')}`}
      </li>)}</ul>
    </>}
    {value?.admin_implicit_access && <p className="text-text-3">{localize('approval.current_visibility.adminHint')}</p>}
    {value?.checked_at && <p className="text-text-3">{localize('approval.current_visibility.checkedAt')} {formatTime(value.checked_at)}</p>}
  </section>;
}
