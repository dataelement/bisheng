import { Button } from '@bisheng/ui';
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { createExternalDepartmentBatch, getExternalDepartmentBatchStatus, previewDepartmentPreset, type DepartmentReceipt } from '@/controllers/API/departmentKnowledgeSpace';
import { showApiError } from '@/controllers/request';
import { useKnowledgePageScope } from '@/hooks/useKnowledgePageScope';

interface Props { ids: number[]; onCreated?: () => void }
type Ticket = {key: string; ids: number[]; refused: number[]};
function readTicket(name: string): Ticket | undefined {
  try {
    const data = JSON.parse(sessionStorage.getItem(name) ?? 'null');
    if (typeof data?.key === 'string' && Array.isArray(data.ids) && data.ids.length > 0 && data.ids.length <= 200 && data.ids.every((id: unknown) => typeof id === 'number' && Number.isSafeInteger(id) && id > 0)) {
      return {key: data.key, ids: data.ids, refused: Array.isArray(data.refused) ? data.refused : []};
    }
  } catch { /* A corrupt or unavailable session cache is not proof of any result. */ }
}

export function DepartmentProviderBatch(props: Props) {
  const { scopes, canManage } = useKnowledgePageScope();
  const scope = scopes?.admin;
  const { t } = useTranslation('bs');
  if (!canManage || !scope) return <p>{t('departmentSpace.batchUnavailable')}</p>;
  const name = `bisheng:department-batch:${scope.tenantId}:${scope.identityKey}`;
  return <BatchForm key={name} {...props} tenant={scope.tenantId} name={name} />;
}

function BatchForm({ ids, tenant, name, onCreated }: Props & {tenant: number; name: string}) {
  const { t } = useTranslation('bs');
  const [ticket, setTicket] = useState(() => readTicket(name));
  const [rows, setRows] = useState<DepartmentReceipt[]>([]);
  const [busy, setBusy] = useState(false);
  const [revision, refresh] = useState(0);
  const [preview, setPreview] = useState<{selection: string; preset: Record<string, unknown>} | null>(null);
  const selection = ids.join(',');
  const mounted = useRef(false);
  const lock = useRef(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    let active = true;
    if (ticket) getExternalDepartmentBatchStatus(tenant, ticket.ids, ticket.key).then(result => {
      if (active) setRows(result.map(row => row.status === 'unconfirmed' && ticket.refused.includes(row.departmentId) ? {...row, status:'failed'} : row));
    }).catch(error => { if (active) showApiError(error); });
    return () => { active = false; };
  }, [tenant, ticket, revision]);
  const valid = ids.length > 0 && ids.length <= 200;
  async function handleAction() {
    if (!valid || lock.current) return;
    lock.current = true; setBusy(true);
    try {
      if (!preview || preview.selection !== selection) {
        const preset = await previewDepartmentPreset(tenant, ids[0]);
        if (mounted.current) setPreview({selection, preset});
        return;
      }
      const next: Ticket = {key: crypto.randomUUID(), ids: [...ids], refused: []};
      sessionStorage.setItem(name, JSON.stringify(next));
      setPreview(null); setRows([]);
      try {
        const result = await createExternalDepartmentBatch(tenant, next.ids, next.key, preview.preset);
        next.refused = result.filter(row => row.status === 'failed').map(row => row.departmentId);
        sessionStorage.setItem(name, JSON.stringify(next));
        if (mounted.current) { setRows(result); onCreated?.(); }
      } finally { if (mounted.current) setTicket(next); }
    } catch (error) { if (mounted.current) showApiError(error); }
    finally { lock.current = false; if (mounted.current) setBusy(false); }
  }
  const ready = preview?.selection === selection;
  return <section aria-live="polite" className="space-y-2">
    {ready && <p>{t('departmentSpace.batchPreset', {revision: String(preview.preset.preset_revision), embedding: String(preview.preset.embedding_model_id), summary: String(preview.preset.summary_model_id), vision: String(preview.preset.vision_model_id)})}</p>}
    <Button disabled={!valid || busy} onClick={handleAction}>{t(ready ? 'departmentSpace.createAction' : 'departmentSpace.batchPreview')}</Button>
    {ticket && <Button variant="outlined" disabled={busy} onClick={() => refresh(n => n + 1)}>{t('departmentSpace.batchRefresh')}</Button>}
    <ul>{rows.map(row => <li key={row.departmentId}>{t('departmentSpace.batchItem', {id:row.departmentId})}: {t(`departmentSpace.batchStatus.${row.status}`)}</li>)}</ul>
  </section>;
}
