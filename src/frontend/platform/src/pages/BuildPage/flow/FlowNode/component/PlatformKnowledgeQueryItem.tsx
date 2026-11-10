import { Input, Select } from '@bisheng/ui';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelectLabels } from '@/components/bs-comp/formFields/useSelectLabels';
import type { KnowledgeQuestion } from '@/types/flow/platformKnowledge';
import { knowledgeOutputs } from '@/controllers/API/platformKnowledge';
import { VarSelectSingleItem } from './VarSelectItem';

interface Props {
    nodeId: string;
    data: { key: string; value: KnowledgeQuestion; varZh?: Record<string, string> };
    onChange: (value: KnowledgeQuestion) => void;
    onValidate: (validate: () => string | false) => void;
    onVarEvent: (validate: () => Promise<string>) => void;
    onOutputChange: (key: string, value: typeof knowledgeOutputs) => void;
}

export function PlatformKnowledgeQueryItem({ nodeId, data, onChange, onValidate, onVarEvent, onOutputChange }: Props) {
    const { t } = useTranslation('flow');
    const labels = useSelectLabels();
    const [question, setQuestion] = useState<KnowledgeQuestion>(data.value ?? { source: 'variable', variable: '' });
    const prefix = 'node.platform_knowledge_retriever.user_question.';
    const variable = { ...data, required: true, value: question.source === 'variable' ? question.variable : '' };

    useEffect(() => {
        if (question.source === 'constant') {
            onValidate(() => question.value.trim() && question.value.length <= 8192 ? false : t('platformKnowledge.invalidQuestion'));
            onVarEvent(async () => '');
        }
    }, [question, onValidate, onVarEvent, t]);

    const update = (value: KnowledgeQuestion) => {
        setQuestion(value);
        onChange(value);
        onOutputChange('retrieved_result', knowledgeOutputs.map(output => ({
            ...output, label: t('node.platform_knowledge_retriever.' + output.key + '.label'),
        })));
    };

    return <div className="nodrag nowheel space-y-2">
        <Select {...labels} aria-label={t('platformKnowledge.questionSource')} value={question.source}
            options={[
                { value: 'variable', label: t('platformKnowledge.variable') },
                { value: 'constant', label: t('platformKnowledge.constant') },
            ]}
            onChange={value => {
                if (value === 'constant') update({ source: 'constant', value: '' });
                if (value === 'variable') update({ source: 'variable', variable: '' });
            }} />
        {question.source === 'variable'
            ? <VarSelectSingleItem nodeId={nodeId} data={variable} i18nPrefix={prefix}
                onChange={(value: string) => {
                    data.varZh = variable.varZh;
                    update({ source: 'variable', variable: value });
                }}
                onValidate={onValidate} onVarEvent={onVarEvent} />
            : <Input aria-label={t(prefix + 'label')} value={question.value} maxLength={8192}
                onChange={event => update({ source: 'constant', value: event.target.value })} />}
    </div>;
}
