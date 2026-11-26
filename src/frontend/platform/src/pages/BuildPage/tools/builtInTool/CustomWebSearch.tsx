import { Button, Textarea } from '@bisheng/ui';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import type { SearchOperation, WebSearchSecret } from '@/controllers/API/webSearch';
import { parseWebSearchSchema, testWebSearch } from '@/controllers/API/webSearch';
import type { OpenApiSchemaSource } from '@/controllers/API/tools';
import { showApiError } from '@/controllers/request';
import { OpenApiSchemaInput } from '../OpenApiSchemaInput';
import { InputField, SelectField } from './InputField';
import type { LegacyDraft } from './customSearchMapping';
import { OpenApiAuthentication } from '../OpenApiAuthentication';
import { normalizeSearchMapping } from './customSearchMapping';
import { OpenApiRequestFields } from './OpenApiRequestFields';

type Auth = { location: string; name: string };
type OpenApiDraft = {
    operation: { version: 2; server: string; method: string; path: string; declaration: Record<string, unknown>; media_type: string; request: unknown; auth: Auth; response_mode: 'raw' | 'mapped' };
    mapping: Record<string, string>;
};
interface Props {
    toolId: string;
    value?: OpenApiDraft | LegacyDraft;
    onChange: (value: OpenApiDraft | LegacyDraft) => void;
    secret: WebSearchSecret;
    onSecretChange: (secret: WebSearchSecret) => void;
    secretConfigured: boolean;
}
export function draftFromOperation(item: SearchOperation): OpenApiDraft {
    return { operation: { version: 2, server: item.server, method: item.method, path: item.path, declaration: item.declaration || {}, media_type: item.media_type || '', request: item.request || {}, auth: item.security || { location: 'none', name: '' }, response_mode: 'raw' }, mapping: normalizeSearchMapping() };
}
function isOpenApiDraft(value: Props['value']): value is OpenApiDraft {
    return Boolean(value?.operation && 'version' in value.operation && value.operation.version === 2);
}
export function CustomWebSearch(props: Props) {
    return <OpenApiSearchForm {...props} value={isOpenApiDraft(props.value) ? props.value : undefined} legacy={Boolean(props.value && !isOpenApiDraft(props.value))} />;
}
interface OpenApiProps extends Omit<Props, 'value'> { value?: OpenApiDraft; legacy: boolean }
function OpenApiSearchForm({ toolId, value, onChange, secret, onSecretChange, secretConfigured, legacy }: OpenApiProps) {
    const { t } = useTranslation();
    const label = (key: string) => String(t('chatConfig.webSearch.' + key, { query: '{{query}}', uuid: '{{uuid}}' }));
    const [content, setContent] = useState('');
    const [operations, setOperations] = useState<SearchOperation[]>([]);
    const [requestText, setRequestText] = useState<string | null>(null);
    const [invalidFields, setInvalidFields] = useState(false);
    const [fieldsRevision, setFieldsRevision] = useState(0);
    const [query, setQuery] = useState('');
    const [preview, setPreview] = useState<unknown>();
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const op = value?.operation;
    const update = (change: Partial<OpenApiDraft['operation']>) => {
        if (value) { onChange({ ...value, operation: { ...value.operation, ...change } }); setPreview(undefined); }
    };
    const selectOperation = (item: SearchOperation) => {
        onChange(draftFromOperation(item)); setRequestText(null); setInvalidFields(false); setPreview(undefined); setError('');
    };
    const handleImport = async (source: OpenApiSchemaSource) => {
        setBusy(true);
        try {
            const result = await parseWebSearchSchema(toolId, source);
            setOperations(result.operations);
            const matching = result.operations.find(item => item.server === op?.server && item.method === op.method && item.path === op.path);
            if (result.operations.length) selectOperation(matching || result.operations[0]);
        } finally { setBusy(false); }
    };
    const handleTest = async () => {
        if (!value) return;
        setBusy(true); setPreview(undefined); setError('');
        try {
            const result = await testWebSearch(toolId, { draft: value, query, secret: secret.action === 'replace' ? secret : { action: 'keep' } });
            setPreview(result.preview);
        } catch (failure) { showApiError(failure); setError(label('testFailed')); }
        finally { setBusy(false); }
    };
    const body = op?.declaration.request_body as { content?: Record<string, unknown> } | undefined;
    const requiredAuth = op?.declaration.security as Auth | null | undefined;
    const chosenIndex = operations.findIndex(item => item.server === op?.server && item.method === op.method && item.path === op.path);
    return <div className="min-w-0 space-y-6">
        <section className="space-y-3">
            <h3 className="font-medium">{label('importSection')}</h3>
            <OpenApiSchemaInput id="custom-schema" value={content} onChange={setContent} onParse={handleImport} disabled={busy} examples={false} />
            {legacy && <p role="note" className="text-sm text-muted-foreground">{label('reimportDeclarations')}</p>}
            {operations.length > 1 && <SelectField id="custom-operation" name="operation" label={label('operation')} value={chosenIndex < 0 ? '' : String(chosenIndex)} options={operations.map((item, index) => ({ value: String(index), label: `${item.method} ${item.server}${item.path}` }))} onChange={(index: string) => selectOperation(operations[Number(index)])} />}
            {op && <p className="break-all text-sm">{op.method} {op.server}{op.path}</p>}
        </section>
        {op && value && <>
            <section className="space-y-3">
                <h3 className="font-medium">{label('requestSection')}</h3>
                {body?.content && Object.keys(body.content).length > 1 && <SelectField id="custom-media" name="media" label={label('mediaType')} value={op.media_type} options={Object.keys(body.content).map(media => ({ value: media, label: media }))} onChange={(media_type: string) => update({ media_type })} />}
                <p className="text-sm text-muted-foreground">{label('parameterValuesHint')}</p>
                <OpenApiRequestFields key={`${op.server}:${op.method}:${op.path}:${op.media_type}:${fieldsRevision}`} declaration={op.declaration} mediaType={op.media_type} value={op.request} onChange={request => { update({ request }); setRequestText(null); }} onValidityChange={setInvalidFields} />
                <details>
                <summary>{label('editRequestJson')}</summary>
                <label htmlFor="custom-request" className="bisheng-label">{label('requestTemplate')}</label>
                <p className="text-sm text-muted-foreground">{label('requestTemplateHint')}</p>
                <Textarea id="custom-request" rows={12} spellCheck={false} value={requestText ?? JSON.stringify(op.request, null, 2)} onChange={event => {
                    const text = event.target.value; setRequestText(text);
                    try { update({ request: JSON.parse(text) }); setFieldsRevision(revision => revision + 1); setInvalidFields(false); setError(''); }
                    catch { update({ request: text }); setError(label('invalidJson')); }
                }} />
                </details>
                <OpenApiAuthentication
                    id="search-auth"
                    value={{ authMethod: op.auth.location === 'none' ? 'none' : 'apikey', authType: 'custom', apiLocation: op.auth.location === 'none' ? 'header' : op.auth.location, parameter: op.auth.name, apiKey: secret.action === 'replace' ? secret.value : '' }}
                    onChange={next => {
                        update({ auth: { location: next.authMethod === 'none' ? 'none' : next.apiLocation, name: next.parameter } });
                        if (next.apiKey !== (secret.action === 'replace' ? secret.value : '')) onSecretChange(next.apiKey ? { action: 'replace', value: next.apiKey } : { action: 'keep' });
                    }}
                    declaredAuth={requiredAuth || undefined}
                    credentialPlaceholder={secretConfigured ? label('secretConfigured') : ''}
                    customOnly
                />
            </section>
            <details className="space-y-3" open={op.response_mode === 'mapped' ? true : undefined}>
                <summary className="font-medium">{label('advancedSettings')}</summary>
                <p className="text-sm text-muted-foreground">{label('rawResponseHint')}</p>
                <SelectField id="custom-response-mode" name="response-mode" label={label('responseSection')} value={op.response_mode} options={[{ value: 'raw', label: label('rawResponse') }, { value: 'mapped', label: label('mappedResults') }]} onChange={(mode: 'raw' | 'mapped') => update({ response_mode: mode })} />
                {op.response_mode === 'mapped' && ['results', 'title', 'url', 'snippet', 'source', 'siteIcon', 'datePublished'].map(key => <InputField key={key} id={'mapping-' + key} name={key} label={label('mapping_' + key)} value={value.mapping[key] || ''} onChange={(event: React.ChangeEvent<HTMLInputElement>) => onChange({ ...value, mapping: { ...value.mapping, [key]: event.target.value } })} />)}
                <details><summary>{label('responseSchema')}</summary><pre className="max-h-48 overflow-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify(op.declaration.responses, null, 2)}</pre></details>
            </details>
            <section className="space-y-3">
                <h3 className="font-medium">{label('testSection')}</h3>
                <InputField id="custom-test-query" name="test-query" label={label('testQuery')} value={query} onChange={(event: React.ChangeEvent<HTMLInputElement>) => setQuery(event.target.value)} />
                <Button type="button" disabled={busy || invalidFields || !query.trim() || typeof op.request !== 'object' || op.request === null} onClick={handleTest}>{label('test')}</Button>
                <p className="text-sm text-muted-foreground">{label('testNotSaved')}</p>
                {error && <p role="alert" className="bisheng-tip">{error}</p>}
                {preview !== undefined && <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-all text-sm">{JSON.stringify(preview, null, 2)}</pre>}
            </section>
        </>}
    </div>;
}
