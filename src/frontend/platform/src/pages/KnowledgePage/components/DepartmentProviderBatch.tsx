import { Button, Input, InputNumber, Select } from '@bisheng/ui';
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  createExternalDepartmentBatch, getExternalDepartmentBatchStatus, listExtractTemplates, listProviderModels, previewDepartmentPreset,
  type DepartmentReceipt, type ExtractConfig, type ExtractTemplate, type ProviderModel, type ProviderModels, type ProviderSelection,
} from '@/controllers/API/departmentKnowledgeSpace';
import { showApiError } from '@/controllers/request';
import { useKnowledgePageScope } from '@/hooks/useKnowledgePageScope';

interface Props { ids: number[]; onCreated?: () => void }
type Ticket = {key: string; ids: number[]; refused: number[]};
type Draft = {
  summary_model_id: string; embedding_model_id: string; vision_model_id: string;
  chunk_size: number | null; overlap: number | null;
  extract_mode: 'template' | 'custom';
  extract_template_kb_id: string;
  extract_config: ExtractConfig;
};
const CHUNK_SIZE_MAX = 100000;
const EMPTY_EXTRACT: ExtractConfig = {
  text: '', tags: [''], nodes: [{ name: '' }], relations: [{ node1: '', type: '', node2: '' }],
};

function readTicket(name: string): Ticket | undefined {
  try {
    const data = JSON.parse(sessionStorage.getItem(name) ?? 'null');
    if (typeof data?.key === 'string' && Array.isArray(data.ids) && data.ids.length > 0 && data.ids.length <= 200 && data.ids.every((id: unknown) => typeof id === 'number' && Number.isSafeInteger(id) && id > 0)) {
      return {key: data.key, ids: data.ids, refused: Array.isArray(data.refused) ? data.refused : []};
    }
  } catch { /* A corrupt or unavailable session cache is not proof of any result. */ }
}

function toSelection(d: Draft): ProviderSelection | null {
  const ids = [d.summary_model_id, d.embedding_model_id, d.vision_model_id];
  if (!ids.every(Boolean) || new Set(ids).size !== 3 || d.chunk_size === null || !Number.isSafeInteger(d.chunk_size)
    || d.chunk_size <= 0 || d.chunk_size > CHUNK_SIZE_MAX || d.overlap === null || !Number.isSafeInteger(d.overlap)
    || d.overlap < 0 || d.overlap >= d.chunk_size) return null;
  const base = {
    summary_model_id: d.summary_model_id, embedding_model_id: d.embedding_model_id, vision_model_id: d.vision_model_id,
    chunk_size: d.chunk_size, overlap: d.overlap,
  };
  if (d.extract_mode === 'template') {
    return d.extract_template_kb_id ? { ...base, extract_template_kb_id: d.extract_template_kb_id } : null;
  }
  const tags = d.extract_config.tags.map(t => t.trim()).filter(Boolean);
  const nodes = d.extract_config.nodes.map(n => ({ name: n.name.trim() })).filter(n => n.name);
  const relations = d.extract_config.relations
    .map(r => ({ node1: r.node1.trim(), type: r.type.trim(), node2: r.node2.trim() }))
    .filter(r => r.node1 && r.type && r.node2);
  const known = new Set(nodes.map(n => n.name));
  if (!d.extract_config.text.trim() || tags.length === 0 || nodes.length === 0 || relations.length === 0
    || known.size !== nodes.length || !relations.every(r => known.has(r.node1) && known.has(r.node2))) return null;
  return { ...base, extract_config: { text: d.extract_config.text.trim(), tags, nodes, relations } };
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
  const [models, setModels] = useState<ProviderModels | null>(null);
  const [modelsFailed, setModelsFailed] = useState(false);
  const [templates, setTemplates] = useState<ExtractTemplate[] | null>(null);
  const [templatesFailed, setTemplatesFailed] = useState(false);
  const [draft, setDraft] = useState<Draft>({
    summary_model_id: '', embedding_model_id: '', vision_model_id: '', chunk_size: 512, overlap: 64,
    extract_mode: 'template', extract_template_kb_id: '', extract_config: EMPTY_EXTRACT,
  });
  const [preview, setPreview] = useState<{selection: string; preset: Record<string, unknown>} | null>(null);
  const chosen = toSelection(draft);
  const selection = `${ids.join(',')}|${JSON.stringify(chosen)}`;
  const mounted = useRef(false);
  const lock = useRef(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    let active = true;
    listProviderModels(tenant).then(result => {
      if (!active) return;
      setModels(result);
      setDraft(d => ({...d, summary_model_id: result.chat[0]?.id ?? '', embedding_model_id: result.embedding[0]?.id ?? '', vision_model_id: result.vision[0]?.id ?? ''}));
    }).catch(() => { if (active) setModelsFailed(true); });
    listExtractTemplates(tenant).then(result => {
      if (!active) return;
      setTemplates(result);
      setDraft(d => ({...d, extract_template_kb_id: d.extract_template_kb_id || result[0]?.id || ''}));
    }).catch(() => { if (active) setTemplatesFailed(true); });
    return () => { active = false; };
  }, [tenant]);
  useEffect(() => {
    let active = true;
    if (ticket) getExternalDepartmentBatchStatus(tenant, ticket.ids, ticket.key).then(result => {
      if (active) setRows(result.map(row => row.status === 'unconfirmed' && ticket.refused.includes(row.departmentId) ? {...row, status:'failed'} : row));
    }).catch(error => { if (active) showApiError(error); });
    return () => { active = false; };
  }, [tenant, ticket, revision]);
  const valid = ids.length > 0 && ids.length <= 200 && chosen !== null;
  async function handleAction() {
    if (!valid || !chosen || lock.current) return;
    lock.current = true; setBusy(true);
    try {
      if (!preview || preview.selection !== selection) {
        const preset = await previewDepartmentPreset(tenant, ids[0], chosen);
        if (mounted.current) setPreview({selection, preset});
        return;
      }
      const next: Ticket = {key: crypto.randomUUID(), ids: [...ids], refused: []};
      sessionStorage.setItem(name, JSON.stringify(next));
      setPreview(null); setRows([]);
      try {
        const result = await createExternalDepartmentBatch(tenant, next.ids, next.key, preview.preset, chosen);
        next.refused = result.filter(row => row.status === 'failed').map(row => row.departmentId);
        sessionStorage.setItem(name, JSON.stringify(next));
        if (mounted.current) { setRows(result); onCreated?.(); }
      } finally { if (mounted.current) setTicket(next); }
    } catch (error) { if (mounted.current) showApiError(error); }
    finally { lock.current = false; if (mounted.current) setBusy(false); }
  }
  const ready = preview?.selection === selection;
  const options = (list: ProviderModel[]) => list.map(m => ({value: m.id, label: m.display_name, description: m.dimension ? `${m.name} · ${m.dimension}` : m.name}));
  const overlapInvalid = draft.chunk_size !== null && draft.overlap !== null && draft.overlap >= draft.chunk_size;
  const setExtract = (patch: Partial<ExtractConfig>) => setDraft(d => ({...d, extract_config: {...d.extract_config, ...patch}}));
  return <section aria-live="polite" className="space-y-2">
    {modelsFailed ? <p role="alert" className="text-danger">{t('departmentSpace.modelsFailed')}</p> : models && <div className="space-y-3">
      <div className="grid grid-cols-2 gap-x-4 gap-y-2">
        {([['summary_model_id', 'pickSummary', models.chat], ['embedding_model_id', 'pickEmbedding', models.embedding], ['vision_model_id', 'pickVision', models.vision]] as const).map(([key, label, list]) =>
          <label key={key} className="space-y-1"><span>{t(`departmentSpace.${label}`)}</span>
            <Select aria-label={t(`departmentSpace.${label}`)} disabled={busy} options={options(list)} placeholder={t('departmentSpace.pickPlaceholder')}
              emptyText={t('departmentSpace.modelsEmpty')} value={draft[key] || null}
              onChange={value => setDraft(d => ({...d, [key]: typeof value === 'string' ? value : ''}))} />
          </label>)}
        <label className="space-y-1"><span>{t('departmentSpace.chunkSize')}</span>
          <InputNumber aria-label={t('departmentSpace.chunkSize')} disabled={busy} min={1} max={CHUNK_SIZE_MAX} precision={0}
            value={draft.chunk_size} onChange={value => setDraft(d => ({...d, chunk_size: value}))} />
        </label>
        <label className="space-y-1"><span>{t('departmentSpace.overlap')}</span>
          <InputNumber aria-label={t('departmentSpace.overlap')} disabled={busy} min={0} precision={0} status={overlapInvalid ? 'error' : undefined}
            value={draft.overlap} onChange={value => setDraft(d => ({...d, overlap: value}))} />
          {overlapInvalid && <span className="text-danger">{t('departmentSpace.overlapInvalid')}</span>}
        </label>
      </div>
      <div className="space-y-2">
        <div className="flex gap-4">
          <label className="flex items-center gap-2">
            <input type="radio" name="extract-mode" disabled={busy} checked={draft.extract_mode === 'template'}
              onChange={() => setDraft(d => ({...d, extract_mode: 'template'}))} />
            <span>{t('departmentSpace.extractFromTemplate')}</span>
          </label>
          <label className="flex items-center gap-2">
            <input type="radio" name="extract-mode" disabled={busy} checked={draft.extract_mode === 'custom'}
              onChange={() => setDraft(d => ({...d, extract_mode: 'custom'}))} />
            <span>{t('departmentSpace.extractCustom')}</span>
          </label>
        </div>
        {draft.extract_mode === 'template' ? (
          templatesFailed ? <p role="alert" className="text-danger">{t('departmentSpace.extractTemplatesFailed')}</p>
            : !templates ? <p>{t('departmentSpace.extractTemplatesLoading')}</p>
              : <label className="block space-y-1"><span>{t('departmentSpace.extractTemplate')}</span>
                <Select aria-label={t('departmentSpace.extractTemplate')} disabled={busy}
                  options={templates.map(row => ({value: row.id, label: row.name, description: row.id}))}
                  placeholder={t('departmentSpace.extractTemplatePlaceholder')}
                  emptyText={t('departmentSpace.extractTemplatesEmpty')}
                  value={draft.extract_template_kb_id || null}
                  onChange={value => setDraft(d => ({...d, extract_template_kb_id: typeof value === 'string' ? value : ''}))} />
              </label>
        ) : <div className="space-y-2">
          <label className="block space-y-1"><span>{t('departmentSpace.extractText')}</span>
            <Input disabled={busy} value={draft.extract_config.text} onChange={e => setExtract({text: e.target.value})} />
          </label>
          <div className="space-y-1">
            <span>{t('departmentSpace.extractTags')}</span>
            {draft.extract_config.tags.map((tag, index) => <div key={`tag-${index}`} className="flex gap-2">
              <Input disabled={busy} value={tag} onChange={e => setExtract({tags: draft.extract_config.tags.map((item, i) => i === index ? e.target.value : item)})} />
              <Button variant="outlined" disabled={busy || draft.extract_config.tags.length <= 1}
                onClick={() => setExtract({tags: draft.extract_config.tags.filter((_, i) => i !== index)})}>{t('departmentSpace.extractRemove')}</Button>
            </div>)}
            <Button variant="outlined" disabled={busy} onClick={() => setExtract({tags: [...draft.extract_config.tags, '']})}>{t('departmentSpace.extractAddTag')}</Button>
          </div>
          <div className="space-y-1">
            <span>{t('departmentSpace.extractNodes')}</span>
            {draft.extract_config.nodes.map((node, index) => <div key={`node-${index}`} className="flex gap-2">
              <Input disabled={busy} value={node.name} onChange={e => setExtract({nodes: draft.extract_config.nodes.map((item, i) => i === index ? {name: e.target.value} : item)})} />
              <Button variant="outlined" disabled={busy || draft.extract_config.nodes.length <= 1}
                onClick={() => setExtract({nodes: draft.extract_config.nodes.filter((_, i) => i !== index)})}>{t('departmentSpace.extractRemove')}</Button>
            </div>)}
            <Button variant="outlined" disabled={busy} onClick={() => setExtract({nodes: [...draft.extract_config.nodes, {name: ''}]})}>{t('departmentSpace.extractAddNode')}</Button>
          </div>
          <div className="space-y-1">
            <span>{t('departmentSpace.extractRelations')}</span>
            {draft.extract_config.relations.map((rel, index) => <div key={`rel-${index}`} className="grid grid-cols-4 gap-2">
              <Input disabled={busy} placeholder={t('departmentSpace.extractRelSource')} value={rel.node1}
                onChange={e => setExtract({relations: draft.extract_config.relations.map((item, i) => i === index ? {...item, node1: e.target.value} : item)})} />
              <Input disabled={busy} placeholder={t('departmentSpace.extractRelType')} value={rel.type}
                onChange={e => setExtract({relations: draft.extract_config.relations.map((item, i) => i === index ? {...item, type: e.target.value} : item)})} />
              <Input disabled={busy} placeholder={t('departmentSpace.extractRelTarget')} value={rel.node2}
                onChange={e => setExtract({relations: draft.extract_config.relations.map((item, i) => i === index ? {...item, node2: e.target.value} : item)})} />
              <Button variant="outlined" disabled={busy || draft.extract_config.relations.length <= 1}
                onClick={() => setExtract({relations: draft.extract_config.relations.filter((_, i) => i !== index)})}>{t('departmentSpace.extractRemove')}</Button>
            </div>)}
            <Button variant="outlined" disabled={busy}
              onClick={() => setExtract({relations: [...draft.extract_config.relations, {node1: '', type: '', node2: ''}]})}>{t('departmentSpace.extractAddRelation')}</Button>
          </div>
        </div>}
      </div>
    </div>}
    {ready && <p>{t('departmentSpace.batchPreset', {revision: String(preview.preset.preset_revision), embedding: String(preview.preset.embedding_model_id), summary: String(preview.preset.summary_model_id), vision: String(preview.preset.vision_model_id), chunk: String(preview.preset.chunk_size), overlap: String(preview.preset.overlap)})}</p>}
    <Button disabled={!valid || busy} onClick={handleAction}>{t(ready ? 'departmentSpace.createAction' : 'departmentSpace.batchPreview')}</Button>
    {ticket && <Button variant="outlined" disabled={busy} onClick={() => refresh(n => n + 1)}>{t('departmentSpace.batchRefresh')}</Button>}
    <ul>{rows.map(row => <li key={row.departmentId}>{t('departmentSpace.batchItem', {id:row.departmentId})}: {t(`departmentSpace.batchStatus.${row.status}`)}</li>)}</ul>
  </section>;
}
