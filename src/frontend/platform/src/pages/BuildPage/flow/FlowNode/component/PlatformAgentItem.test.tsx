/** 覆盖 AC: AC-01, AC-02, AC-03, AC-04, AC-05, AC-20, AC-23。 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useContext, useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PlatformAgentItem } from './PlatformAgentItem';
import type { PlatformAgentBindings, PlatformAgentReference } from '@/types/flow';
import { userContext } from '@/contexts/userContext';
import { getPlatformAgentCapabilities, getPlatformAgents, getPlatformAgentVersion, validatePlatformAgents } from '@/controllers/API/workflow';

vi.mock('@/controllers/API/workflow', () => ({
    getPlatformAgentCapabilities: vi.fn(async () => ({ platform_agent_enabled: true, platform_agent_mode: 'mock', platform_agent_policy_revision: 'v1' })),
    getPlatformAgents: vi.fn(async () => ({ data: [{ agent_id: '', name: 'invalid', versions: [] }, { agent_id: 'echo', name: 'Echo', versions: ['v1', 'v2'] }], has_more: false })),
    getPlatformAgentVersion: vi.fn(async (_workflow, agent, version) => ({ ref: { agent_id: agent, version_id: version }, available: true, can_use: true, input_schema: { type: 'object', properties: { value: {} } }, output_schema: { type: 'object' } })),
    validatePlatformAgents: vi.fn(async () => ({ valid: true, issues: [] })),
}));
vi.mock('@/controllers/request', () => ({ showApiError: vi.fn() }));
vi.mock('./SelectVar', () => ({ default: ({ children }: { children: React.ReactNode }) => <>{children}</> }));
vi.mock('@/contexts/userContext', async () => ({ userContext: (await import('react')).createContext({ user: { user_id: 12, tenant_id: 7 } }) }));
// 使用可操作的选择器桩。测试配置状态与接口调用契约。
vi.mock('@bisheng/ui', () => ({
    Select: ({ options, value, onChange, ...props }: { options: { value: string; label: string }[]; value: string; onChange: (value: string) => void; 'aria-label': string }) => <select aria-label={props['aria-label']} value={value || ''} onChange={e => onChange(e.target.value)}><option value="">--</option>{options.map(row => <option key={row.value} value={row.value}>{row.label}</option>)}</select>,
    Textarea: (props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) => <textarea {...props} />,
    Input: (props: React.InputHTMLAttributes<HTMLInputElement>) => <input {...props} />,
    Button: (props: React.ButtonHTMLAttributes<HTMLButtonElement>) => <button {...props} />,
    Checkbox: ({ label, checked, disabled, onCheckedChange }: { label: string; checked: boolean; disabled: boolean; onCheckedChange: (value: boolean) => void }) =>
        <label>{label}<input type="checkbox" checked={checked} disabled={disabled} onChange={event => onCheckedChange(event.target.checked)} /></label>,
}));

describe('PlatformAgentItem', () => {
    afterEach(() => { cleanup(); vi.clearAllMocks(); });
    it.each([
        { available: true, supported: true, mode: 'async', enabled: true },
        { available: false, supported: true, mode: 'async', enabled: false },
        { available: true, supported: false, mode: 'async', enabled: false },
        { available: true, supported: true, mode: 'sync', enabled: false },
    ] as const)('gates interaction on isolation, pinned version and async mode: $available $supported $mode', async ({ available, supported, mode, enabled }) => {
        const optionsChanged = vi.fn();
        let validate = () => false as string | false;
        vi.mocked(getPlatformAgentVersion).mockImplementationOnce(async () => ({
            ref: { agent_id: 'echo', version_id: 'v1' }, available: true, can_use: true, provider_mode: 'mock',
            policy_revision: 'v1', supports_async: true, supports_interaction: supported,
            long_tasks_available: true, interaction_available: available, input_schema: { type: 'object' },
            output_schema: { type: 'object' },
        }));
        const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
        function Harness() {
            const [reference, setReference] = useState<PlatformAgentReference | null>({ agent_id: 'echo', version_id: 'v1' });
            const [allowed, setAllowed] = useState(false);
            return <PlatformAgentItem workflowId="flow" nodeId="platform_agent_1" reference={reference} bindings={{}}
                executionMode={mode} allowInteraction={allowed} onChange={setReference}
                onOptionsChange={(executionMode, allowInteraction) => { optionsChanged(executionMode, allowInteraction); setAllowed(allowInteraction); }}
                onValidate={next => { validate = next; }} />;
        }
        render(<QueryClientProvider client={client}><Harness /></QueryClientProvider>);
        const toggle = await screen.findByRole('checkbox', { name: 'platformAgent.allowInteraction' });
        expect(toggle).not.toBeChecked();
        if (!enabled) {
            expect(toggle).toBeDisabled();
            return;
        }
        expect(toggle).toBeEnabled();
        fireEvent.click(toggle);
        expect(optionsChanged).toHaveBeenCalledWith('async', true);
        await waitFor(() => expect(validatePlatformAgents).toHaveBeenLastCalledWith('flow',
            expect.objectContaining({ nodes: [expect.objectContaining({ data: expect.objectContaining({
                group_params: [{ params: expect.arrayContaining([{ key: 'allow_interaction', value: true }]) }],
            }) })] }), 'platform_agent_1'));
        fireEvent.change(screen.getByLabelText('platformAgent.version'), { target: { value: 'v2' } });
        await screen.findByText('platformAgent.interactionUnsupported');
        expect(screen.getByRole('checkbox', { name: 'platformAgent.allowInteraction' })).toBeChecked();
        expect(validate()).toBe('platformAgent.interactionUnsupported');
    });
    it.each([
        { user: { user_id: 12, leaf_tenant_id: 7 }, multiTenant: true },
        { user: { user_id: 12 }, multiTenant: false },
    ])('loads mock agents and versions for existing user-info shapes: $user', async ({ user, multiTenant }) => {
        vi.mocked(getPlatformAgentCapabilities).mockResolvedValueOnce({ platform_agent_enabled: true, platform_agent_mode: 'mock', platform_agent_policy_revision: 'v1', multi_tenant_enabled: multiTenant });
        function Harness() {
            const defaults = useContext(userContext);
            const [reference, setReference] = useState<PlatformAgentReference | null>(null);
            return <userContext.Provider value={{ ...defaults, user }}><PlatformAgentItem workflowId="flow" nodeId="platform_agent_1" reference={reference} bindings={{}} onChange={next => setReference(next)} onValidate={() => {}} /></userContext.Provider>;
        }
        render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><Harness /></QueryClientProvider>);
        expect(await screen.findByRole('option', { name: 'Echo' })).toBeInTheDocument();
        fireEvent.change(screen.getByLabelText('platformAgent.agent'), { target: { value: 'echo' } });
        fireEvent.change(screen.getByLabelText('platformAgent.version'), { target: { value: 'v1' } });
        await screen.findByLabelText('value');
        expect(getPlatformAgents).toHaveBeenCalledWith('flow', undefined);
        expect(getPlatformAgentVersion).toHaveBeenCalledWith('flow', 'echo', 'v1');
    });

    it('reports missing multi-tenant identity without loading another tenant directory', async () => {
        vi.mocked(getPlatformAgentCapabilities).mockResolvedValueOnce({ platform_agent_enabled: true, platform_agent_mode: 'mock', platform_agent_policy_revision: 'v1', multi_tenant_enabled: true });
        function Harness() {
            const defaults = useContext(userContext);
            return <userContext.Provider value={{ ...defaults, user: { user_id: 12 } }}><PlatformAgentItem workflowId="flow" nodeId="platform_agent_1" reference={null} bindings={{}} onChange={() => {}} onValidate={() => {}} /></userContext.Provider>;
        }
        render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><Harness /></QueryClientProvider>);
        expect(await screen.findByText('platformAgent.identityNotReady')).toBeInTheDocument();
        expect(getPlatformAgents).not.toHaveBeenCalled();
    });

    it('keeps draft version and JSON values and identifies simulated data', async () => {
        let latest: PlatformAgentBindings = {};
        function Harness() {
            const [ref, setRef] = useState<PlatformAgentReference | null>({ agent_id: 'echo', version_id: 'v1' });
            const [bindings, setBindings] = useState<PlatformAgentBindings>({ value: { source: 'constant', value: 0 } });
            return <PlatformAgentItem workflowId="flow" nodeId="platform_agent_1" reference={ref} bindings={bindings} onChange={(next, values) => { latest = values; setRef(next); setBindings(values); }} onValidate={() => {}} />;
        }
        render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><Harness /></QueryClientProvider>);
        expect(await screen.findByText('platformAgent.mock')).toBeInTheDocument();
        expect(await screen.findByLabelText('value')).toHaveValue('0');
        expect(screen.queryByText('invalid')).not.toBeInTheDocument();
        fireEvent.change(screen.getByLabelText('value'), { target: { value: 'false' } });
        await waitFor(() => expect(latest.value).toEqual({ source: 'constant', value: false }));
        fireEvent.change(screen.getByLabelText('platformAgent.version'), { target: { value: 'v2' } });
        expect(await screen.findByText('platformAgent.versionChanged')).toBeInTheDocument();
    });

    it('lets the author remove obsolete mappings after changing the version', async () => {
        vi.mocked(getPlatformAgentVersion).mockImplementationOnce(async () => ({ ref: { agent_id: 'echo', version_id: 'v1' }, available: true, can_use: true, provider_mode: 'mock', policy_revision: 'v1', input_schema: { type: 'object', properties: { query: { type: 'string' } } }, output_schema: { type: 'object' } }))
            .mockImplementationOnce(async () => ({ ref: { agent_id: 'echo', version_id: 'v2' }, available: true, can_use: true, provider_mode: 'mock', policy_revision: 'v1', input_schema: { type: 'object', properties: { question: { type: 'string' } }, additionalProperties: false }, output_schema: { type: 'object' } }));
        let latest: PlatformAgentBindings = {};
        function Harness() {
            const [ref, setRef] = useState<PlatformAgentReference | null>({ agent_id: 'echo', version_id: 'v1' });
            const [bindings, setBindings] = useState<PlatformAgentBindings>({ query: { source: 'constant', value: 'hello' } });
            return <PlatformAgentItem workflowId="flow" nodeId="platform_agent_1" reference={ref} bindings={bindings} onChange={(next, values) => { latest = values; setRef(next); setBindings(values); }} onValidate={() => {}} />;
        }
        render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><Harness /></QueryClientProvider>);
        await screen.findByLabelText('query');
        fireEvent.change(screen.getByLabelText('platformAgent.version'), { target: { value: 'v2' } });
        await screen.findByLabelText('question');
        expect(latest.query).toBeDefined();
        fireEvent.click(screen.getByRole('button', { name: 'query platformAgent.removeBinding' }));
        fireEvent.change(screen.getByLabelText('question'), { target: { value: 'new question' } });
        await waitFor(() => expect(latest).toEqual({ question: { source: 'constant', value: 'new question' } }));
    });

    it.each(['tenant_id', 'leaf_tenant_id'] as const)('isolates directory caches when %s changes', async tenantField => {
        vi.mocked(getPlatformAgents).mockResolvedValueOnce({ data: [{ agent_id: 'private', name: 'Private resource', versions: ['v1'] }], has_more: false, next_cursor: null, provider_mode: 'mock', policy_revision: 'v1' })
            .mockResolvedValueOnce({ data: [], has_more: false, next_cursor: null, provider_mode: 'mock', policy_revision: 'v1' });
        const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
        function Harness() {
            const defaults = useContext(userContext);
            const [user, setUser] = useState({ user_id: 12, [tenantField]: 7 });
            return <userContext.Provider value={{ ...defaults, user }}><button onClick={() => setUser({ user_id: 12, [tenantField]: 8 })}>Switch</button><PlatformAgentItem workflowId="flow" nodeId="platform_agent_1" reference={null} bindings={{}} onChange={() => {}} onValidate={() => {}} /></userContext.Provider>;
        }
        render(<QueryClientProvider client={client}><Harness /></QueryClientProvider>);
        expect(await screen.findByRole('option', { name: 'Private resource' })).toBeInTheDocument();
        fireEvent.click(screen.getByText('Switch'));
        expect(screen.queryByRole('option', { name: 'Private resource' })).not.toBeInTheDocument();
        await waitFor(() => expect(screen.getByText('platformAgent.empty')).toBeInTheDocument());
    });

    it('distinguishes failed resource queries from an empty directory', async () => {
        vi.mocked(getPlatformAgents).mockRejectedValueOnce(new Error('fixture outage'));
        render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><PlatformAgentItem workflowId="flow" nodeId="platform_agent_1" reference={null} bindings={{}} onChange={() => {}} onValidate={() => {}} /></QueryClientProvider>);
        expect(await screen.findByText('platformAgent.queryFailed')).toBeInTheDocument();
        expect(screen.queryByText('platformAgent.empty')).not.toBeInTheDocument();
    });
});
