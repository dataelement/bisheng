import { useState } from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';

import { OpenApiRequestFields } from './OpenApiRequestFields';

afterEach(cleanup);
it('lists declared fields and edits nested JSON without dropping other request values', () => {
    function Harness() {
        const [value, setValue] = useState<Record<string, unknown>>({ query: { extra: 'keep' }, body: { model: '', input: '', tools: [{ type: 'web_search' }], custom: 7 } });
        const [invalid, setInvalid] = useState(false);
        return <><OpenApiRequestFields declaration={{ parameters: [], request_body: { content: { 'application/json': { schema: { type: 'object', required: ['model', 'input', 'tools'], properties: { model: { type: 'string', description: 'Model ID' }, input: { oneOf: [{ type: 'string' }, { type: 'array' }] }, tools: { type: 'array' }, include: { type: 'array' } } } } } } }} mediaType="application/json" value={value} onChange={setValue} onValidityChange={setInvalid} /><button disabled={invalid}>Test request</button><output>{JSON.stringify(value)}</output></>;
    }
    render(<Harness />);
    expect(screen.getByText('Model ID')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/model/), { target: { value: 'gpt-6.1-sol' } });
    fireEvent.change(screen.getByLabelText(/input/), { target: { value: '{{query}}' } });
    fireEvent.change(screen.getByLabelText(/tools/), { target: { value: '[{"type":"web_search"},{"type":"another"}]' } });
    expect(JSON.parse(screen.getByRole('status').textContent || '{}')).toEqual({ query: { extra: 'keep' }, body: { model: 'gpt-6.1-sol', input: '{{query}}', tools: [{ type: 'web_search' }, { type: 'another' }], custom: 7 } });
    fireEvent.change(screen.getByLabelText(/tools/), { target: { value: '[invalid' } });
    expect(screen.getByLabelText(/tools/)).toHaveValue('[invalid');
    expect(screen.getByRole('button', { name: 'Test request' })).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/tools/), { target: { value: '[]' } });
    expect(screen.getByRole('button', { name: 'Test request' })).toBeEnabled();
});

it('keeps root array request bodies as arrays', () => {
    let saved: unknown;
    render(<OpenApiRequestFields declaration={{ request_body: { required: true, content: { 'application/json': { schema: { type: 'array', items: { type: 'object' } } } } } }} mediaType="application/json" value={{ body: [{ q: 'first' }] }} onChange={value => { saved = value; }} onValidityChange={() => {}} />);
    fireEvent.change(screen.getByLabelText(/body/), { target: { value: '[{"q":"{{query}}"},{"q":"second"}]' } });
    expect(saved).toEqual({ body: [{ q: '{{query}}' }, { q: 'second' }] });
});

it('shows descriptions declared on query parameters', () => {
    let saved: unknown;
    render(<OpenApiRequestFields declaration={{ parameters: [{ name: 'q', location: 'query', required: true, description: 'Search keywords', schema: { type: 'string' } }] }} mediaType="" value={{ query: { q: '{{query}}' }, header: { 'X-Custom': 'preserve' } }} onChange={value => { saved = value; }} onValidityChange={() => {}} />);
    expect(screen.getByText('Search keywords')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/q/), { target: { value: 'updated' } });
    expect(saved).toEqual({ query: { q: 'updated' }, header: { 'X-Custom': 'preserve' } });
});
