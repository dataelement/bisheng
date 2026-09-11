import { Badge } from '@/components/bs-ui/badge';
import { Button } from '@/components/bs-ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/bs-ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/bs-ui/tabs';
import { useToast } from '@/components/bs-ui/toast/use-toast';
import { copyText } from '@/utils';
import { Clipboard } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/cjs/styles/prism';
import { assistantExamples, workflowExamples, type ApiIdentityMode, type PublishedApiKind } from './apiRequestExamples';

interface ApiRequestExamplesProps {
    kind: PublishedApiKind;
    applicationId: string;
}

export function ApiRequestExamples({ kind, applicationId }: ApiRequestExamplesProps) {
    const { t } = useTranslation();
    const { message } = useToast();
    const [identity, setIdentity] = useState<ApiIdentityMode>('service');
    const options = { origin: location.origin, applicationId, identity, question: t('api.assistantDoc.hello') };
    const examples = kind === 'assistant' ? assistantExamples(options) : workflowExamples(options);
    const handleCopy = async (code: string) => {
        try {
            await copyText(code);
            message({ variant: 'success', description: t('api.copySuccess') });
        } catch {
            message({ variant: 'error', description: t('api.openApiGuide.copy_failed') });
        }
    };

    return <Card className="mb-8">
        <CardHeader><CardTitle>{t('api.apiRequestExample')}</CardTitle></CardHeader>
        <CardContent className="space-y-4 text-sm leading-6">
            {kind === 'assistant' && <div className="bg-secondary px-4 py-2 inline-flex items-center rounded-md gap-1">
                <Badge>POST</Badge>
                <button type="button" className="hover:underline break-all text-left" onClick={() => void handleCopy('/api/v2/assistant/chat/completions')}>/api/v2/assistant/chat/completions</button>
            </div>}
            <p>{t('api.openApiGuide.examples_setup', { scope: kind === 'assistant' ? 'assistant:invoke' : 'workflow:invoke' })}</p>
            <Tabs value={identity} onValueChange={value => {
                if (value === 'service' || value === 'delegate' || value === 'external') setIdentity(value);
            }}>
                <TabsList className="h-auto flex-wrap justify-start">
                    {(['service', 'delegate', 'external'] as const).map(mode => <TabsTrigger key={mode} value={mode}>{t(`api.openApiGuide.${mode}_title`)}</TabsTrigger>)}
                </TabsList>
                {(['service', 'delegate', 'external'] as const).map(mode => <TabsContent key={mode} value={mode}>
                    <p>{t(`api.openApiGuide.example_${mode}`)}</p>
                </TabsContent>)}
            </Tabs>
            <Tabs defaultValue="curl">
                <TabsList className="h-auto flex-wrap justify-start">
                    {Object.keys(examples).map(key => <TabsTrigger key={key} value={key}>{key === 'python' ? 'Python API' : key === 'curl' && kind === 'assistant' ? 'cURL' : t(`api.openApiGuide.example_${key}_tab`)}</TabsTrigger>)}
                </TabsList>
                {Object.entries(examples).map(([key, code]) => <TabsContent key={key} value={key}>
                    <div className="mb-2 flex justify-end">
                        <Button type="button" size="sm" variant="outline" onClick={() => void handleCopy(code)}>
                            <Clipboard size={15} className="mr-1.5" />{t('api.openApiGuide.copy_example')}
                        </Button>
                    </div>
                    <SyntaxHighlighter className="w-full overflow-auto custom-scroll" language={key === 'python' ? 'python' : 'bash'} style={oneDark}>{code}</SyntaxHighlighter>
                </TabsContent>)}
            </Tabs>
            <p className="text-muted-foreground">{t(`api.openApiGuide.${kind}_note`)}</p>
        </CardContent>
    </Card>;
}
