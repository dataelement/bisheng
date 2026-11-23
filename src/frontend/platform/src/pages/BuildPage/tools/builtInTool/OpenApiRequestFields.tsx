import { Checkbox, Input, Textarea } from '@bisheng/ui';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/bs-ui/table';

type JsonObject = Record<string, unknown>;
type RequestField = { name: string; location: string; required: boolean; schema: JsonObject; root?: boolean };
const object = (value: unknown): JsonObject => value !== null && typeof value === 'object' && !Array.isArray(value) ? value as JsonObject : {};

function fieldsFromSchema(declaration: JsonObject, mediaType: string): RequestField[] {
    const fields: RequestField[] = [];
    for (const raw of Array.isArray(declaration.parameters) ? declaration.parameters : []) {
        const param = object(raw);
        if (typeof param.name === 'string' && typeof param.location === 'string') fields.push({ name: param.name, location: param.location, required: param.required === true, schema: { ...object(param.schema), ...(typeof param.description === 'string' ? { description: param.description } : {}) } });
    }
    const body = object(declaration.request_body);
    const schema = object(object(object(body.content)[mediaType]).schema);
    const properties = object(schema.properties);
    if (Object.keys(properties).length && (!schema.type || schema.type === 'object')) {
        for (const [name, child] of Object.entries(properties)) fields.push({ name, location: 'body', required: Array.isArray(schema.required) && schema.required.includes(name), schema: object(child) });
    } else if (Object.keys(object(body.content)).length) {
        fields.push({ name: 'body', location: 'body', root: true, required: body.required === true, schema });
    }
    return fields;
}
function isText(schema: JsonObject, value: unknown): boolean {
    if (schema.type === 'string') return true;
    const variants = schema.oneOf || schema.anyOf;
    return typeof value === 'string' && Array.isArray(variants) && variants.some(item => object(item).type === 'string');
}
function FieldValue({ id, field, value, onChange, onValidityChange }: { id: string; field: RequestField; value: unknown; onChange: (value: unknown) => void; onValidityChange: (invalid: boolean) => void }) {
    const { t } = useTranslation();
    const text = isText(field.schema, value);
    const display = (next: unknown) => text ? String(next ?? '') : next === undefined ? '' : JSON.stringify(next, null, 2);
    const [draft, setDraft] = useState({ source: value, text: display(value) });
    const [invalid, setInvalid] = useState(false);
    const current = draft.source === value ? draft.text : display(value);
    const handleChange = (raw: string) => {
        let parsed: unknown = raw;
        let invalid = false;
        if (!text) {
            try { parsed = JSON.parse(raw); } catch { invalid = true; }
        }
        setDraft({ source: parsed, text: raw });
        setInvalid(invalid);
        onChange(parsed);
        onValidityChange(invalid);
    };
    return <>
        {text ? <Input id={id} value={current} onChange={event => handleChange(event.target.value)} /> : <Textarea id={id} rows={field.schema.type === 'number' || field.schema.type === 'integer' || field.schema.type === 'boolean' ? 1 : 4} spellCheck={false} value={current} onChange={event => handleChange(event.target.value)} />}
        {invalid && <p role="alert" className="bisheng-tip">{t('chatConfig.webSearch.invalidJson')}</p>}
    </>;
}
interface Props {
    declaration: JsonObject;
    mediaType: string;
    value: unknown;
    onChange: (value: JsonObject) => void;
    onValidityChange: (invalid: boolean) => void;
}

/** List declared fields while preserving the complete request, including extra properties. */
export function OpenApiRequestFields({ declaration, mediaType, value, onChange, onValidityChange }: Props) {
    const { t } = useTranslation();
    const [invalidFields, setInvalidFields] = useState<Record<string, boolean>>({});
    const fields = fieldsFromSchema(declaration, mediaType);
    const request = object(value);
    const update = (field: RequestField, next: unknown, include = true) => {
        const result = { ...request };
        if (field.root) {
            if (include) result.body = next; else delete result.body;
        } else {
            const section = { ...object(result[field.location]) };
            if (include) section[field.name] = next; else delete section[field.name];
            result[field.location] = section;
        }
        onChange(result);
    };
    const markInvalid = (key: string, invalid: boolean) => {
        const next = { ...invalidFields, [key]: invalid };
        setInvalidFields(next);
        onValidityChange(Object.values(next).some(Boolean));
    };
    if (!fields.length) return null;
    return <Table>
        <TableHeader><TableRow><TableHead>{t('test.parameter')}</TableHead><TableHead>{t('tools.description')}</TableHead><TableHead>{t('test.value')}</TableHead></TableRow></TableHeader>
        <TableBody>{fields.map(field => {
            const key = field.location + ':' + field.name;
            const id = 'search-param-' + key;
            const section = object(request[field.location]);
            const included = field.root ? Object.hasOwn(request, 'body') : Object.hasOwn(section, field.name);
            const current = field.root ? request.body : section[field.name];
            return <TableRow key={key}>
                <TableCell><label htmlFor={id}>{field.name}{field.required && <span className="bisheng-tip"> *</span>}</label><p className="text-xs text-muted-foreground">{field.location}</p></TableCell>
                <TableCell className="max-w-48 whitespace-normal break-words">{typeof field.schema.description === 'string' ? field.schema.description : ''}</TableCell>
                <TableCell className="min-w-48">
                    {!field.required && <Checkbox label={String(t('chatConfig.webSearch.includeParameter')) + ': ' + field.name} checked={included} onCheckedChange={checked => { update(field, isText(field.schema, '') ? '' : field.schema.type === 'array' ? [] : field.schema.type === 'object' ? {} : null, checked === true); markInvalid(key, false); }} />}
                    {(field.required || included) && <FieldValue id={id} field={field} value={current} onChange={next => update(field, next)} onValidityChange={invalid => markInvalid(key, invalid)} />}
                </TableCell>
            </TableRow>;
        })}</TableBody>
    </Table>;
}
