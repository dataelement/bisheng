import { Button } from '@bisheng/ui';
import { useLocalize } from '~/hooks';
import type { ProviderUploadRow } from '../hooks/useProviderFileUploads';

interface ProviderUploadResultsProps {
  items: ProviderUploadRow[];
  onRetry: (key: string) => void;
  onCheck: (key: string) => void;
}
const labels = {
  accepted: 'com_knowledge.provider_upload_received',
  conflict: 'com_knowledge.provider_upload_conflict',
  not_sent: 'com_knowledge.provider_upload_not_sent',
  reupload_required: 'com_knowledge.provider_upload_missing',
  sending: 'com_knowledge.provider_upload_sending',
  unknown: 'com_knowledge.provider_upload_unknown',
} as const;
export function ProviderUploadResults({ items, onRetry, onCheck }: ProviderUploadResultsProps) {
  const localize = useLocalize();
  if (!items.length) return null;
  return <ul aria-live="polite" className="max-h-40 shrink-0 overflow-y-auto px-4 text-body-sm text-text-2">
    {items.map(item => <li key={item.key} className="flex items-center gap-2 py-1">
      <span className="min-w-0 truncate" title={item.name}>{item.name}</span><span>{localize(labels[item.state])}</span>
      {(item.state === 'not_sent' || item.state === 'reupload_required') && <Button size="small" variant="text" disabled={item.busy} onClick={() => onRetry(item.key)}>{localize('com_knowledge.retry')}</Button>}
      {item.state === 'unknown' && <Button size="small" variant="text" disabled={item.busy} onClick={() => onCheck(item.key)}>{localize('com_knowledge.provider_upload_check')}</Button>}
    </li>)}
  </ul>;
}
