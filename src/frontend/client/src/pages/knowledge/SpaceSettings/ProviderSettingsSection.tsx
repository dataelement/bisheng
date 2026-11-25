import { Radio, RadioGroup } from '@bisheng/ui';
import type { ProviderConfig, SpaceProvider } from '~/api/knowledgeProviderSettings';
import { SettingsSectionHeader } from '~/components/permission/UnifiedPermissionControls';
import { useLocalize } from '~/hooks';

interface Props {
  creating: boolean;
  provider: SpaceProvider | null;
  onChange: (provider: SpaceProvider) => void;
  config?: ProviderConfig;
  failed: boolean;
  pending?: boolean;
  disabled: boolean;
}
export function ProviderSettingsSection({ creating, provider, onChange, config, failed, pending, disabled }: Props) {
  const localize = useLocalize();
  const flags = ['wiki_enabled', 'entities_enabled', 'multimodal_enabled', 'auto_tag_enabled', 'vector_index_enabled', 'keyword_index_enabled'] as const;
  const rows = config ? [
    ['preset_revision', config.preset_revision],
    ['preset_summary_model', `${config.summary_model_id} · ${config.summary_version}`],
    ['preset_embedding_model', `${config.embedding_model_id} · ${config.embedding_version}`],
    ['preset_dimensions', config.embedding_dimension],
    ['preset_vision_model', `${config.vision_model_id} · ${config.vision_version}`],
    ['preset_wiki_model', config.wiki_model_id ?? localize('com_knowledge.preset_inherit')],
    ['preset_tag_model', config.tag_model_id ?? localize('com_knowledge.preset_inherit')],
    ['preset_chunk_size', config.chunk_size], ['preset_overlap', config.overlap],
    ...flags.map(key => [`preset_${key}`, localize(config[key] ? 'com_knowledge.preset_on' : 'com_knowledge.preset_off')]),
  ] : [];
  if (!creating && provider !== 'weknora') return null;
  return <section className="space-y-4">
    <SettingsSectionHeader kind="advanced" title={localize('com_knowledge.provider_settings')} />
    {creating && <RadioGroup value={provider ?? ''} disabled={disabled} aria-label={localize('com_knowledge.provider_settings')} onValueChange={v => onChange(v === 'weknora' ? 'weknora' : 'native')}>
      <Radio value="native">{localize('com_knowledge.provider_native')}</Radio>
      <Radio value="weknora">WeKnora</Radio>
    </RadioGroup>}
    {provider === 'weknora' && <>
      <p className="text-body-sm text-text-2">{localize(creating ? 'com_knowledge.preset_create_hint' : 'com_knowledge.preset_read_only')}</p>
      {pending && <p role="status">{localize('com_knowledge.preset_pending')}</p>}
      {failed ? <p role="alert" className="text-body text-danger">{localize('com_knowledge.preset_unavailable')}</p> : config ?
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-body-sm">{rows.map(([key, value]) => <div key={key} className="contents">
          <dt className="text-text-2">{localize(`com_knowledge.${key}`)}</dt><dd className="break-words text-text-1">{value}</dd>
        </div>)}</dl> : <p role="status">{localize('com_ui_loading')}</p>}
    </>}
  </section>;
}
