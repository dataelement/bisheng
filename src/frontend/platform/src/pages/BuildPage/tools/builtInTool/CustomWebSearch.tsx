import { Button, Checkbox, notification } from '@bisheng/ui';
import { parseWebSearchSchema, SearchOperation, SearchProof, testWebSearch, WebSearchSecret } from '@/controllers/API/webSearch';
import { ChangeEvent, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { InputField, SelectField } from './InputField';
import { normalizeSearchMapping } from './customSearchMapping';
import { OpenApiSchemaInput } from '../OpenApiSchemaInput';
import type { OpenApiSchemaSource } from '@/controllers/API/tools';

type Parameter = { location: string; name: string };
type Draft = {
    operation: { server: string; method: string; path: string; query_parameter: Parameter; fixed_params: { location: string; name: string; value: string | number | boolean }[]; auth: { location: string; name: string } };
    mapping: Record<string, string>;
    proof?: SearchProof;
};
interface Props {
    toolId: string;
    value?: Draft;
    onChange: (value: Draft) => void;
    secret: WebSearchSecret;
    onSecretChange: (secret: WebSearchSecret) => void;
    secretConfigured: boolean;
}
const empty: Draft = { operation: { server: '', method: '', path: '', query_parameter: { location: '', name: '' }, fixed_params: [], auth: { location: 'none', name: '' } }, mapping: normalizeSearchMapping() };

export function CustomWebSearch({ toolId, value = empty, onChange, secret, onSecretChange, secretConfigured }: Props) {
    const { t } = useTranslation();
    const [content, setContent] = useState('');
    const [operations, setOperations] = useState<SearchOperation[]>([]);
    const [query, setQuery] = useState('');
    const [preview, setPreview] = useState<{ status: string; preview: unknown; results: unknown } | null>(null);
    const [busy, setBusy] = useState(false);
    const op = value.operation || empty.operation;
    const mapping = normalizeSearchMapping(value.mapping);
    const savedOperation: SearchOperation | undefined = op.server && op.method && op.path ? { server: op.server, method: op.method, path: op.path, proof: value.proof || { key_id: '', ciphertext: '' }, security: op.auth?.location === 'header' || op.auth?.location === 'query' ? { location: op.auth.location, name: op.auth.name } : null, parameters: [ ...(op.query_parameter?.name ? [{ ...op.query_parameter, type: 'string', required: true }] : []),  ] } : undefined;
    const candidates = operations.length ? operations : savedOperation ? [savedOperation] : [];
    const selected = candidates.find(item => item.server === op.server && item.method === op.method && item.path === op.path);
    const hasDeclaration = operations.some(item => item.server === op.server && item.method === op.method && item.path === op.path);
    const canEditAuth = hasDeclaration && selected?.security === null;
    const label = (key: string) => String(t('chatConfig.webSearch.' + key));
    const updateOp = (change: Partial<Draft['operation']>) => onChange({ ...value, operation: { ...op, ...change }, mapping });
    const handleImport = async (source: OpenApiSchemaSource) => {
        setBusy(true);
        try {
            const result = await parseWebSearchSchema(toolId, source);
            setOperations(result.operations);
            const matching = result.operations.find(item => item.server === op.server && item.method === op.method && item.path === op.path);
            if (matching) onChange({ ...value, operation: { ...op, auth: matching.security || op.auth || { location: 'none', name: '' } }, mapping, proof: matching.proof });
            setPreview(null);
        } finally { setBusy(false); }
    };
    const handleTest = async () => {
        setBusy(true);
        setPreview(null);
        try {
            const testSecret = secret.action === 'replace' ? secret : { action: 'keep' as const };
            setPreview(await testWebSearch(toolId, { draft: { ...value, mapping }, query, secret: testSecret }));
        } catch {
            notification.open({ type: 'error', title: String(t('failed')), description: label('testFailed') });
        } finally { setBusy(false); }
    };
    return <div className="space-y-4">
        <OpenApiSchemaInput id="custom-schema" value={content} onChange={setContent} onParse={handleImport} disabled={busy} examples={false} parseOnBlur={false} />
        {!value.proof?.key_id || !value.proof?.ciphertext ? <p role="status">{label('proofRequired')}</p> : null}
        <SelectField id="custom-operation" name="custom-operation" label={label('operation')} value={selected ? String(candidates.indexOf(selected)) : ''} options={candidates.map((item, index) => ({ value: String(index), label: item.method.toUpperCase() + ' ' + item.path }))} onChange={(index: string) => {
            const item = candidates[Number(index)];
            onChange({ ...value, operation: { ...op, server: item.server, method: item.method, path: item.path, auth: item.security || { location: 'none', name: '' }, query_parameter: { location: '', name: '' }, fixed_params: [] }, mapping, proof: item.proof });
        }} />
        {savedOperation && !hasDeclaration && <div role="note"><p>{label('reimportDeclarations')}</p>{(op.fixed_params || []).map(p => <p key={p.location + ':' + p.name}>{p.location}: {p.name} = {String(p.value)}</p>)}</div>}
        <SelectField id="custom-query-parameter" name="custom-query-parameter" label={label('queryParameter')} value={op.query_parameter?.name ? op.query_parameter.location + ':' + op.query_parameter.name : ''} options={(selected?.parameters || []).filter(item => item.type === 'string').map(item => ({ value: item.location + ':' + item.name, label: item.location + ': ' + item.name }))} onChange={(key: string) => {
            const item = selected?.parameters.find(p => p.location + ':' + p.name === key);
            if (item) updateOp({ query_parameter: { location: item.location, name: item.name }, fixed_params: (op.fixed_params || []).filter(p => p.location !== item.location || p.name !== item.name) });
        }} />
        {(selected?.parameters || []).filter(p => p.location !== op.query_parameter?.location || p.name !== op.query_parameter?.name).map(p => {
            const current = op.fixed_params?.find(item => item.location === p.location && item.name === p.name);
            const setFixed = (newValue: string | number | boolean | undefined) => {
                const rest = (op.fixed_params || []).filter(item => item.location !== p.location || item.name !== p.name);
                updateOp({ fixed_params: newValue === undefined ? rest : [...rest, { location: p.location, name: p.name, value: newValue }] });
            };
            const fieldLabel = label('fixedParameter') + ': ' + p.name + ' (' + p.type + ')';
            const id = 'fixed-' + p.location + '-' + p.name;
            if (p.type === 'boolean') return <SelectField key={id} id={id} name={p.name} label={fieldLabel} required={p.required} value={current ? String(current.value) : ''} options={[{ value: 'true', label: 'true' }, { value: 'false', label: 'false' }]} onChange={(next: string) => setFixed(next === 'true')} />;
            const field = <InputField id={id} name={p.name} label={fieldLabel} required={p.required} type={p.type === 'number' || p.type === 'integer' ? 'number' : 'text'} min={undefined} step={p.type === 'number' ? 'any' : p.type === 'integer' ? 1 : undefined} value={String(current?.value ?? '')} onChange={(e: ChangeEvent<HTMLInputElement>) => {
                const raw = e.target.value;
                setFixed(p.type === 'string' ? raw : raw === '' ? undefined : Number(raw));
            }} />;
            if (p.type !== 'string') return <div key={id}>{field}</div>;
            return <div key={id}>
                <Checkbox label={label('includeParameter') + ': ' + p.name} checked={Boolean(current)} onCheckedChange={(checked) => setFixed(checked === true ? '' : undefined)} />
                {field}
            </div>;
        })}
        {canEditAuth ? <SelectField id="custom-auth" name="custom-auth" label={label('authentication')} value={op.auth?.location || 'none'} options={[{ value: 'none', label: label('noAuth') }, { value: 'header', label: label('header') }, { value: 'query', label: label('query') }]} onChange={(location: string) => updateOp({ auth: { location, name: '' } })} /> : <InputField id="custom-auth" name="custom-auth" label={label('authentication')} value={label(op.auth?.location === 'header' ? 'header' : op.auth?.location === 'query' ? 'query' : 'noAuth')} readOnly onChange={() => {}} />}
        {op.auth?.location !== 'none' && <>
            <InputField id="auth-name" name="auth-name" label={label('authName')} value={op.auth?.name || ''} readOnly={!canEditAuth} onChange={(e: ChangeEvent<HTMLInputElement>) => updateOp({ auth: { ...op.auth, name: e.target.value } })} />
            <InputField id="auth-secret" name="auth-secret" type="password" label={label('secret')} placeholder={secretConfigured ? label('secretConfigured') : ''} value={secret.action === 'replace' ? secret.value : ''} onChange={(e: ChangeEvent<HTMLInputElement>) => onSecretChange(e.target.value ? { action: 'replace', value: e.target.value } : { action: 'keep' })} />
        </>}
        {['results', 'title', 'url', 'snippet', 'source', 'siteIcon', 'datePublished'].map(key => <InputField key={key} id={'mapping-' + key} name={key} label={label('mapping_' + key)} value={mapping[key] || ''} onChange={(e: ChangeEvent<HTMLInputElement>) => onChange({ ...value, operation: op, mapping: { ...mapping, [key]: e.target.value } })} />)}
        <InputField id="custom-test-query" name="custom-test-query" label={label('testQuery')} value={query} onChange={(e: ChangeEvent<HTMLInputElement>) => setQuery(e.target.value)} />
        <Button type="button" disabled={busy || !query.trim() || !value.proof?.key_id || !value.proof?.ciphertext} onClick={handleTest}>{label('test')}</Button>
        {preview && <div><p>{preview.status}</p><p>{label('rawResponse')}</p><pre className="whitespace-pre-wrap break-all">{JSON.stringify(preview.preview, null, 2)}</pre><p>{label('mappedResults')}</p><pre className="whitespace-pre-wrap break-all">{JSON.stringify(preview.results, null, 2)}</pre></div>}
    </div>;
}
