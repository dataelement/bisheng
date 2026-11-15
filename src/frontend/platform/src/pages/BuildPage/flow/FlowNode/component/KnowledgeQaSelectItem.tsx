// @ts-strict-ignore
import { Label } from '@/components/bs-ui/label';
import { useSelectLabels } from '@/components/bs-comp/formFields/useSelectLabels';
import { useKnowledgeCandidates } from '@/components/bs-comp/selectComponent/useKnowledgeCandidates';
import { Select } from '@bisheng/ui';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

export default function KnowledgeQaSelectItem({ data, onChange, onValidate, onVarEvent, i18nPrefix }) {
    const { t } = useTranslation('flow');
    const selectLabels = useSelectLabels();
    const candidates = useKnowledgeCandidates('qa');
    const value = data.value.map(item => ({ label: item.label, value: item.key }));
    const saved = new Map(value.map(item => [String(item.value), item]));
    const options = candidates.options.map(item => ({ ...item, value: saved.get(String(item.value))?.value ?? item.value }));
    const known = new Set(options.map(item => String(item.value)));
    // Disabled placeholders retain labels and IDs without enabling a new binding.
    const displayed = [...options, ...value.filter(item => !known.has(String(item.value))).map(item => ({ ...item, disabled: true }))];
    const [error, setError] = useState(false);
    useEffect(() => {
        onValidate(() => {
            const missing = data.required && !data.value.length;
            setError(!!missing);
            return missing ? `${t(`${i18nPrefix}label`)} ${t('required')}` : false;
        });
        return () => onValidate(() => {});
    }, [data.value]);
    useEffect(() => {
        // Candidate absence does not establish deletion or revoke an existing saved slot.
        onVarEvent?.(() => '');
        return () => onVarEvent?.(() => {});
    }, [data.value]);
    return <div className="node-item mb-4">
        <Label className="flex items-center bisheng-label mb-2">
            {data.required && <span className="text-red-500">*</span>}{t(`${i18nPrefix}label`)}
        </Label>
        <Select {...selectLabels} id="knowledge-qaselect" multiple showSearch className="nodrag"
            status={error ? 'error' : 'default'} value={value.map(item => item.value)} options={displayed}
            placeholder={t(`${i18nPrefix}placeholder`)} aria-label={t(`${i18nPrefix}label`)}
            onChange={(ids) => onChange(ids.map(id => {
                const old = data.value.find(item => String(item.key) === String(id));
                return old ?? { key: id, label: options.find(item => String(item.value) === String(id))?.label ?? String(id) };
            }))}
            onOpenChange={open => { if (open) candidates.refresh(); }} onSearch={candidates.search}
            onLoadMore={candidates.loadMore} loading={candidates.loading} loadingMore={candidates.loadingMore} />
        {value.some(item => !known.has(String(item.value))) && <p className="text-xs text-text-3">{t('references.unconfirmed', { ns: 'bs' })}</p>}
    </div>;
}
