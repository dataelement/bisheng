import { Button, Input, InputNumber, Radio, RadioGroup, Select } from '@bisheng/ui';
import {
  CHUNK_SIZE_MAX, type ExtractConfig, type ExtractTemplate, type ProviderConfig, type ProviderModel, type ProviderModels, type ReviewedPreset, type SpaceProvider,
} from '~/api/knowledgeProviderSettings';
import { SettingsSectionHeader } from '~/components/permission/UnifiedPermissionControls';
import { useLocalize } from '~/hooks';
import type { SelectionDraft } from './useProviderPreset';

export interface ProviderPicker {
  models: ProviderModels | null;
  modelsFailed: boolean;
  templates: ExtractTemplate[] | null;
  templatesFailed: boolean;
  selection: SelectionDraft;
  setSelection: (update: (current: SelectionDraft) => SelectionDraft) => void;
  complete: boolean;
  preset: ReviewedPreset | null;
  /** The shown preset is still being re-reviewed for the current selection. */
  refreshing?: boolean;
}
interface Props {
  creating: boolean;
  provider: SpaceProvider | null;
  onChange: (provider: SpaceProvider) => void;
  config?: ProviderConfig;
  failed: boolean;
  pending?: boolean;
  disabled: boolean;
  picker?: ProviderPicker;
}

function updateExtract(config: ExtractConfig, patch: Partial<ExtractConfig>): ExtractConfig {
  return { ...config, ...patch };
}

function ExtractForm({ picker, disabled }: { picker: ProviderPicker; disabled: boolean }) {
  const localize = useLocalize();
  const { selection, setSelection, templates, templatesFailed } = picker;
  const extract = selection.extract_config;
  const setExtract = (patch: Partial<ExtractConfig>) => setSelection(current => ({
    ...current, extract_config: updateExtract(current.extract_config, patch),
  }));
  return <div className="space-y-3">
    <div className="space-y-2">
      {/* Names the rule set these radios choose between, so the source is not read as chunking. */}
      <span className="text-body-sm text-text-2">{localize('com_knowledge.provider_extract_mode')}</span>
      <RadioGroup
        value={selection.extract_mode}
        disabled={disabled}
        aria-label={localize('com_knowledge.provider_extract_mode')}
        onValueChange={value => setSelection(current => ({
          ...current, extract_mode: value === 'custom' ? 'custom' : 'template',
        }))}
      >
        <Radio value="template">{localize('com_knowledge.provider_extract_from_template')}</Radio>
        <Radio value="custom">{localize('com_knowledge.provider_extract_custom')}</Radio>
      </RadioGroup>
    </div>
    {selection.extract_mode === 'template' ? (
      templatesFailed ? <p role="alert" className="text-body text-danger">{localize('com_knowledge.provider_extract_templates_failed')}</p>
        : !templates ? <p role="status">{localize('com_ui_loading')}</p>
          : <label className="block space-y-1">
            <span className="text-body-sm text-text-2">{localize('com_knowledge.provider_extract_template')}</span>
            <Select
              aria-label={localize('com_knowledge.provider_extract_template')}
              disabled={disabled}
              options={templates.map(t => ({ value: t.id, label: t.name, description: t.id }))}
              placeholder={localize('com_knowledge.provider_extract_template_placeholder')}
              emptyText={localize('com_knowledge.provider_extract_templates_empty')}
              value={selection.extract_template_kb_id || null}
              onChange={value => setSelection(current => ({
                ...current, extract_template_kb_id: typeof value === 'string' ? value : '',
              }))}
            />
          </label>
    ) : <div className="space-y-3">
      <label className="block space-y-1">
        <span className="text-body-sm text-text-2">{localize('com_knowledge.provider_extract_text')}</span>
        <Input
          aria-label={localize('com_knowledge.provider_extract_text')}
          disabled={disabled}
          value={extract.text}
          onChange={event => setExtract({ text: event.target.value })}
        />
      </label>
      <div className="space-y-2">
        <span className="text-body-sm text-text-2">{localize('com_knowledge.provider_extract_tags')}</span>
        {extract.tags.map((tag, index) => <div key={`tag-${index}`} className="flex gap-2">
          <Input
            aria-label={`${localize('com_knowledge.provider_extract_tags')} ${index + 1}`}
            disabled={disabled}
            value={tag}
            onChange={event => setExtract({ tags: extract.tags.map((item, i) => i === index ? event.target.value : item) })}
          />
          <Button variant="outlined" color="default" disabled={disabled || extract.tags.length <= 1}
            onClick={() => setExtract({ tags: extract.tags.filter((_, i) => i !== index) })}>
            {localize('com_knowledge.provider_extract_remove')}
          </Button>
        </div>)}
        <Button variant="outlined" color="default" disabled={disabled} onClick={() => setExtract({ tags: [...extract.tags, ''] })}>
          {localize('com_knowledge.provider_extract_add_tag')}
        </Button>
      </div>
      <div className="space-y-2">
        <span className="text-body-sm text-text-2">{localize('com_knowledge.provider_extract_nodes')}</span>
        {extract.nodes.map((node, index) => <div key={`node-${index}`} className="flex gap-2">
          <Input
            aria-label={`${localize('com_knowledge.provider_extract_nodes')} ${index + 1}`}
            disabled={disabled}
            value={node.name}
            onChange={event => setExtract({
              nodes: extract.nodes.map((item, i) => i === index ? { name: event.target.value } : item),
            })}
          />
          <Button variant="outlined" color="default" disabled={disabled || extract.nodes.length <= 1}
            onClick={() => setExtract({ nodes: extract.nodes.filter((_, i) => i !== index) })}>
            {localize('com_knowledge.provider_extract_remove')}
          </Button>
        </div>)}
        <Button variant="outlined" color="default" disabled={disabled} onClick={() => setExtract({ nodes: [...extract.nodes, { name: '' }] })}>
          {localize('com_knowledge.provider_extract_add_node')}
        </Button>
      </div>
      <div className="space-y-2">
        <span className="text-body-sm text-text-2">{localize('com_knowledge.provider_extract_relations')}</span>
        {extract.relations.map((rel, index) => <div key={`rel-${index}`} className="grid grid-cols-[1fr_1fr_1fr_auto] gap-2 max-[768px]:grid-cols-1">
          <Input aria-label={`${localize('com_knowledge.provider_extract_rel_source')} ${index + 1}`} disabled={disabled}
            placeholder={localize('com_knowledge.provider_extract_rel_source')}
            value={rel.node1}
            onChange={event => setExtract({
              relations: extract.relations.map((item, i) => i === index ? { ...item, node1: event.target.value } : item),
            })} />
          <Input aria-label={`${localize('com_knowledge.provider_extract_rel_type')} ${index + 1}`} disabled={disabled}
            placeholder={localize('com_knowledge.provider_extract_rel_type')}
            value={rel.type}
            onChange={event => setExtract({
              relations: extract.relations.map((item, i) => i === index ? { ...item, type: event.target.value } : item),
            })} />
          <Input aria-label={`${localize('com_knowledge.provider_extract_rel_target')} ${index + 1}`} disabled={disabled}
            placeholder={localize('com_knowledge.provider_extract_rel_target')}
            value={rel.node2}
            onChange={event => setExtract({
              relations: extract.relations.map((item, i) => i === index ? { ...item, node2: event.target.value } : item),
            })} />
          <Button variant="outlined" color="default" disabled={disabled || extract.relations.length <= 1}
            onClick={() => setExtract({ relations: extract.relations.filter((_, i) => i !== index) })}>
            {localize('com_knowledge.provider_extract_remove')}
          </Button>
        </div>)}
        <Button variant="outlined" color="default" disabled={disabled}
          onClick={() => setExtract({ relations: [...extract.relations, { node1: '', type: '', node2: '' }] })}>
          {localize('com_knowledge.provider_extract_add_relation')}
        </Button>
      </div>
    </div>}
  </div>;
}

function ProviderChoices({ picker, disabled }: { picker: ProviderPicker; disabled: boolean }) {
  const localize = useLocalize();
  const { models, selection, setSelection } = picker;
  if (picker.modelsFailed) return <p role="alert" className="text-body text-danger">{localize('com_knowledge.provider_models_failed')}</p>;
  if (!models) return <p role="status">{localize('com_ui_loading')}</p>;
  const options = (list: ProviderModel[]) => list.map(m => ({
    value: m.id, label: m.display_name, description: m.dimension ? `${m.name} · ${m.dimension}` : m.name,
  }));
  const fields = [
    ['summary_model_id', 'provider_pick_summary', models.chat],
    ['embedding_model_id', 'provider_pick_embedding', models.embedding],
    ['vision_model_id', 'provider_pick_vision', models.vision],
  ] as const;
  const overlapInvalid = selection.chunk_size !== null && selection.overlap !== null && selection.overlap >= selection.chunk_size;
  return <div className="space-y-4">
    <div className="grid grid-cols-2 gap-x-4 gap-y-3 max-[768px]:grid-cols-1">
      {fields.map(([key, label, list]) => <label key={key} className="space-y-1">
        <span className="text-body-sm text-text-2">{localize(`com_knowledge.${label}`)}</span>
        <Select aria-label={localize(`com_knowledge.${label}`)} disabled={disabled} options={options(list)}
          placeholder={localize('com_knowledge.provider_pick_placeholder')} emptyText={localize('com_knowledge.provider_models_empty')}
          value={selection[key] || null} onChange={value => setSelection(current => ({ ...current, [key]: typeof value === 'string' ? value : '' }))} />
      </label>)}
      <label className="space-y-1">
        <span className="text-body-sm text-text-2">{localize('com_knowledge.preset_chunk_size')}</span>
        <InputNumber aria-label={localize('com_knowledge.preset_chunk_size')} disabled={disabled} min={1} max={CHUNK_SIZE_MAX} precision={0}
          value={selection.chunk_size} onChange={value => setSelection(current => ({ ...current, chunk_size: value }))} />
      </label>
      <label className="space-y-1">
        <span className="text-body-sm text-text-2">{localize('com_knowledge.preset_overlap')}</span>
        <InputNumber aria-label={localize('com_knowledge.preset_overlap')} disabled={disabled} min={0} precision={0}
          status={overlapInvalid ? 'error' : undefined}
          value={selection.overlap} onChange={value => setSelection(current => ({ ...current, overlap: value }))} />
        {overlapInvalid && <span className="text-body-sm text-danger">{localize('com_knowledge.provider_overlap_invalid')}</span>}
      </label>
    </div>
    <ExtractForm picker={picker} disabled={disabled} />
  </div>;
}

export function ProviderSettingsSection({ creating, provider, onChange, config, failed, pending, disabled, picker }: Props) {
  const localize = useLocalize();
  const flags = ['wiki_enabled', 'entities_enabled', 'multimodal_enabled', 'auto_tag_enabled', 'vector_index_enabled', 'keyword_index_enabled'] as const;

  // Which extraction-rule configuration the preset was built from. Read from the
  // reviewed preset (not the live draft) so the label always describes the exact
  // configuration shown below, even while a new preview is still in flight.
  const extractRule = (() => {
    const selection = picker?.preset?.selection;
    if (!selection) return localize('com_knowledge.preset_extract_rule_configured');
    if (selection.extract_template_kb_id) {
      const template = picker?.templates?.find(one => one.id === selection.extract_template_kb_id);
      return template
        ? localize('com_knowledge.preset_extract_rule_from_template', { name: template.name })
        : localize('com_knowledge.preset_extract_rule_configured');
    }
    return localize('com_knowledge.preset_extract_rule_custom');
  })();

  const rows = config ? [
    ['preset_revision', config.preset_revision],
    ['preset_summary_model', `${config.summary_model_id} · ${config.summary_version}`],
    ['preset_embedding_model', `${config.embedding_model_id} · ${config.embedding_version}`],
    ['preset_dimensions', config.embedding_dimension],
    ['preset_vision_model', `${config.vision_model_id} · ${config.vision_version}`],
    ['preset_wiki_model', config.wiki_model_id ?? localize('com_knowledge.preset_inherit')],
    ['preset_tag_model', config.tag_model_id ?? localize('com_knowledge.preset_inherit')],
    ['preset_chunk_size', config.chunk_size], ['preset_overlap', config.overlap],
    // Sits next to the extraction flag so "what governs extraction" is answered
    // before the on/off switch that only says whether extraction runs at all.
    ['preset_extract_rule', extractRule],
    ...flags.map(key => [`preset_${key}`, localize(config[key] ? 'com_knowledge.preset_on' : 'com_knowledge.preset_off')]),
  ] : [];
  if (!creating && provider !== 'weknora') return null;
  const choosing = creating && picker && !picker.modelsFailed && picker.models && !picker.complete;
  return <section className="space-y-4">
    <SettingsSectionHeader kind="advanced" title={localize('com_knowledge.provider_settings')} />
    {creating && <RadioGroup value={provider ?? ''} disabled={disabled} aria-label={localize('com_knowledge.provider_settings')} onValueChange={v => onChange(v === 'weknora' ? 'weknora' : 'native')}>
      <Radio value="native">{localize('com_knowledge.provider_native')}</Radio>
      <Radio value="weknora">WeKnora</Radio>
    </RadioGroup>}
    {provider === 'weknora' && <>
      <p className="text-body-sm text-text-2">{localize(creating ? 'com_knowledge.preset_create_hint' : 'com_knowledge.preset_read_only')}</p>
      {creating && picker && <ProviderChoices picker={picker} disabled={disabled} />}
      {pending && <p role="status">{localize('com_knowledge.preset_pending')}</p>}
      {creating && picker && (picker.modelsFailed || !picker.models) ? null
        : choosing ? <p className="text-body-sm text-text-2">{localize('com_knowledge.provider_pick_required')}</p>
        : failed ? <p role="alert" className="text-body text-danger">{localize('com_knowledge.preset_unavailable')}</p> : config ?
        <>
          {picker?.refreshing && <p role="status">{localize('com_ui_loading')}</p>}
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-body-sm">{rows.map(([key, value]) => <div key={key} className="contents">
            <dt className="text-text-2">{localize(`com_knowledge.${key}`)}</dt><dd className="break-words text-text-1">{value}</dd>
          </div>)}</dl>
          <p className="text-body-sm text-text-2">{localize('com_knowledge.preset_extract_rule_hint')}</p>
        </> : <p role="status">{localize('com_ui_loading')}</p>}
    </>}
  </section>;
}
