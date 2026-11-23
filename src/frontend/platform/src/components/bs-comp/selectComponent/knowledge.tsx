import MultiSelect from '@/components/bs-ui/select/multi';
import { Tabs } from '@bisheng/ui';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useKnowledgeCandidates } from './useKnowledgeCandidates';

interface KnowledgeOption {
    value: string | number;
    label: string;
    type?: string;
}
interface KnowledgeSelectProps {
    type?: 'file' | 'qa' | 'space' | 'all';
    multiple?: boolean;
    className?: string;
    value: KnowledgeOption[];
    disabled?: boolean;
    enableSpace?: boolean;
    errorKeys?: string[];
    onChange: (value: KnowledgeOption[]) => void;
    children?: (refresh: () => void) => React.ReactNode;
}

export default function KnowledgeSelect({ type = 'all', multiple = false, className = '', value,
    disabled = false, enableSpace = false, errorKeys = [], onChange, children }: KnowledgeSelectProps) {
    const { t } = useTranslation();
    const [tab, setTab] = useState<'space' | 'qa'>(type === 'qa' ? 'qa' : 'space');
    const candidates = useKnowledgeCandidates(tab);
    const saved = new Map(value.map(item => [String(item.value), item]));
    const options = candidates.options.map(item => ({ ...item, value: String(item.value) }));
    const handleChange = (values: { value: string; label: string }[]) => onChange(values.map(item =>
        saved.get(String(item.value)) ?? candidates.options.find(option => String(option.value) === item.value) ?? { ...item, type: tab }
    ));
    return <><MultiSelect
        id="knowledge-select"
        tabs={type === 'all' && !enableSpace ? <Tabs activeKey={tab} onChange={next => setTab(next as 'space' | 'qa')}
            items={[{ key: 'space', label: t('build.knowledgeSpace') }, { key: 'qa', label: t('lib.qaData') }]} /> : null}
        multiple={multiple} className={className} value={value.map(item => ({ ...item, value: String(item.value) }))} disabled={disabled}
        errorKeys={errorKeys} options={options} placeholder={t('build.selectKnowledgeBase')}
        searchPlaceholder={t('build.searchBaseName')} onChange={handleChange}
        onLoad={candidates.refresh} onSearch={candidates.search} onScrollLoad={candidates.loadMore}
    >{children?.(candidates.refresh)}</MultiSelect>
        {value.some(item => !options.some(option => option.value === String(item.value))) &&
            <p className="text-xs text-text-3">{t('references.unconfirmed')}</p>}
    </>;
}
