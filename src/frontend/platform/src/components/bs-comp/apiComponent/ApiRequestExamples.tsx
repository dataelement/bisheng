import { Button, toast } from '@bisheng/ui';
import { Tag, Tabs } from '@bisheng/ui';
import { Outlined } from 'bisheng-icons';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/bs-ui/card';

import { copyText } from '@/utils';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/cjs/styles/prism';
import { assistantExamples, workflowExamples, type ApiIdentityMode, type PublishedApiKind } from './apiRequestExampleBuilders';

interface ApiRequestExamplesProps {
    kind: PublishedApiKind;
    applicationId: string;
}

export function ApiRequestExamples({ kind, applicationId }: ApiRequestExamplesProps) {
    const { t } = useTranslation();

    const [identity, setIdentity] = useState<ApiIdentityMode>('service');
    const options = { origin: location.origin, applicationId, identity, question: t('api.assistantDoc.hello') };
    const examples = kind === 'assistant' ? assistantExamples(options) : workflowExamples(options);
    const handleCopy = async (code: string) => {
        try {
            await copyText(code);
            toast.show({ type: 'success', message: String(t('api.copySuccess') ?? '') });
        } catch {
            toast.show({ type: 'error', message: String(t('api.openApiGuide.copy_failed') ?? '') });
        }
    };

    return <Card className="mb-8">
        <CardHeader><CardTitle>{t('api.apiRequestExample')}</CardTitle></CardHeader>
        <CardContent className="space-y-4 text-sm leading-6">
            {kind === 'assistant' && <div className="bg-secondary px-4 py-2 inline-flex items-center rounded-md gap-1">
                <Tag size="small" color="brand">POST</Tag>
                <button type="button" className="hover:underline break-all text-left" onClick={() => void handleCopy('/api/v2/assistant/chat/completions')}>/api/v2/assistant/chat/completions</button>
            </div>}
            <p>{t('api.openApiGuide.examples_setup', { scope: kind === 'assistant' ? 'assistant:invoke' : 'workflow:invoke' })}</p>
            <Tabs activeKey={identity} onChange={value => {
                if (value === 'service' || value === 'delegate' || value === 'external') setIdentity(value);
            }} items={(['service', 'delegate', 'external'] as const).map(mode => ({
                key: mode,
                label: t(`api.openApiGuide.${mode}_title`),
                children: <p>{t(`api.openApiGuide.example_${mode}`)}</p>,
            }))} />
            <Tabs defaultActiveKey="curl" items={Object.entries(examples).map(([key, code]) => ({
                key,
                label: key === 'python' ? 'Python API' : key === 'curl' && kind === 'assistant' ? 'cURL' : t(`api.openApiGuide.example_${key}_tab`),
                children: <>
                    <div className="mb-2 flex justify-end">
                        <Button type="button" size="small" variant="outlined" onClick={() => void handleCopy(code)} color="default">
                            <Outlined.Copy size={15} className="mr-1.5" />{t('api.openApiGuide.copy_example')}
                        </Button>
                    </div>
                    <SyntaxHighlighter className="w-full overflow-auto custom-scroll" language={key === 'python' ? 'python' : 'bash'} style={oneDark}>{code}</SyntaxHighlighter>
                </>,
            }))} />
            <p className="text-muted-foreground">{t(`api.openApiGuide.${kind}_note`)}</p>
        </CardContent>
    </Card>;
}
