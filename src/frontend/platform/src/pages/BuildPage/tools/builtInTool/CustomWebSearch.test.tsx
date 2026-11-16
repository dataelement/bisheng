import { useState } from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { CustomWebSearch } from './CustomWebSearch';

const api = vi.hoisted(() => ({ parseWebSearchSchema: vi.fn(), testWebSearch: vi.fn() }));
vi.mock('@/controllers/API/webSearch', () => api);
vi.mock('@/controllers/request', () => ({ showApiError: vi.fn() }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });
it('imports a sole operation, edits nested parameters and previews an arbitrary response', async () => {
    api.parseWebSearchSchema.mockResolvedValue({ operations: [{ version: 2, server: 'https://search.example', method: 'POST', path: '/find', declaration: { security: { location: 'header', name: '' }, request_body: { content: { 'application/json': {} } }, responses: {} }, media_type: 'application/json', request: { body: { commands: { queries: [{ q: '' }] } } }, proof: { key_id: 'v1', ciphertext: 'sealed' }, security: { location: 'header', name: '' }, parameters: [] }] });
    api.testWebSearch.mockResolvedValue({ status: 'success', preview: { answer: 'complete result', extra: [1, 2] }, results: { answer: 'complete result' } });
    function Harness() {
        const [value, setValue] = useState<React.ComponentProps<typeof CustomWebSearch>['value']>();
        return <CustomWebSearch toolId="16" value={value} onChange={setValue} secret={{ action: 'replace', value: 'Bearer fixture' }} onSecretChange={() => {}} secretConfigured={false} />;
    }
    render(<Harness />);
    const schema = screen.getByLabelText('OpenAPI Schema');
    fireEvent.change(schema, { target: { value: 'openapi: 3.0.3' } });
    fireEvent.blur(schema);
    const editor = await screen.findByLabelText('chatConfig.webSearch.requestTemplate');
    const request = { body: { commands: { queries: [{ q: '{{query}}' }, { q: 'second' }] } } };
    fireEvent.change(editor, { target: { value: JSON.stringify(request) } });
    fireEvent.change(screen.getByLabelText('tools.parameterName'), { target: { value: 'Authorization' } });
    fireEvent.change(screen.getByLabelText('chatConfig.webSearch.testQuery'), { target: { value: 'keyword' } });
    fireEvent.click(screen.getByRole('button', { name: 'chatConfig.webSearch.test' }));
    await waitFor(() => expect(api.testWebSearch).toHaveBeenCalledWith('16', expect.objectContaining({ query: 'keyword', draft: expect.objectContaining({ operation: expect.objectContaining({ version: 2, request, response_mode: 'raw', auth: { location: 'header', name: 'Authorization' } }) }) })));
    expect(await screen.findByText(/complete result/)).toBeInTheDocument();
    fireEvent.change(editor, { target: { value: '{invalid' } });
    expect(screen.getByRole('button', { name: 'chatConfig.webSearch.test' })).toBeDisabled();
    expect(editor).toHaveValue('{invalid');
    fireEvent.blur(schema);
    expect(api.parseWebSearchSchema).toHaveBeenCalledTimes(1);
    expect(screen.queryByText('chatConfig.webSearch.queryParameter')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('chatConfig.webSearch.mapping_results')).not.toBeInTheDocument();
});

it('opens saved legacy settings with the common import UI and no obsolete search fields', () => {
    render(<CustomWebSearch toolId="16" value={{ operation: { server: 'https://old.example', method: 'GET', path: '/find', query_parameter: { location: 'query', name: 'q' }, fixed_params: [], auth: { location: 'none', name: '' } }, mapping: {} }} onChange={() => {}} secret={{ action: 'keep' }} onSecretChange={() => {}} secretConfigured={false} />);
    expect(screen.getByLabelText('OpenAPI Schema')).toBeInTheDocument();
    expect(screen.getByRole('note')).toHaveTextContent('chatConfig.webSearch.reimportDeclarations');
    expect(screen.queryByLabelText('chatConfig.webSearch.queryParameter')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('chatConfig.webSearch.mapping_results')).not.toBeInTheDocument();
});

it('selects the first of multiple imported operations and follows replacement schema authentication', async () => {
    const item = { version: 2, server: 'https://search.example', method: 'GET', path: '/one', declaration: { security: { location: 'header', name: 'X-Key' } }, request: {}, proof: { key_id: 'v1', ciphertext: 'sealed' }, security: { location: 'header', name: 'X-Key' }, parameters: [] };
    api.parseWebSearchSchema.mockResolvedValueOnce({ operations: [item, { ...item, path: '/two' }] }).mockResolvedValueOnce({ operations: [{ ...item, path: '/public', declaration: { security: null }, security: null }] });
    function Harness() {
        const [value, setValue] = useState<React.ComponentProps<typeof CustomWebSearch>['value']>();
        return <CustomWebSearch toolId="16" value={value} onChange={setValue} secret={{ action: 'keep' }} onSecretChange={() => {}} secretConfigured={false} />;
    }
    render(<Harness />);
    const schema = screen.getByLabelText('OpenAPI Schema');
    fireEvent.change(schema, { target: { value: 'first schema' } });
    fireEvent.blur(schema);
    expect(await screen.findByLabelText('tools.parameterName')).toHaveValue('X-Key');
    expect(screen.getAllByText('GET https://search.example/one').length).toBeGreaterThan(0);
    expect(screen.getByLabelText('tools.none')).toBeDisabled();
    fireEvent.change(schema, { target: { value: 'public schema' } });
    fireEvent.blur(schema);
    await waitFor(() => expect(screen.queryByLabelText('tools.parameterName')).not.toBeInTheDocument());
    expect(screen.getByLabelText('tools.none')).toBeChecked();
});
