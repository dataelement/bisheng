import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ApiError } from '@bisheng/api-client';
import { act, render, screen, waitFor } from '@testing-library/react';
import { useContext } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { userContext } from '@/contexts/userContext';
import { getKnowledgeCapabilities, getPlatformKnowledge, listPlatformKnowledge } from '@/controllers/API/platformKnowledge';
import { PlatformKnowledgeSelectItem } from './PlatformKnowledgeSelectItem';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock('@/components/bs-comp/formFields/useSelectLabels', () => ({ useSelectLabels: () => ({}) }));
vi.mock('@/controllers/API/platformKnowledge', () => ({
    getKnowledgeCapabilities: vi.fn(),
    getPlatformKnowledge: vi.fn(),
    listPlatformKnowledge: vi.fn(),
}));
vi.mock('@bisheng/ui', () => ({
    Button: 'button',
    Select: ({ options }: { options: { value: string; label: string }[] }) =>
        <select>{options.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</select>,
}));

describe('platform knowledge selection', () => {
    it.each([true, false])('scopes authorized directory to the current tenant (%s)', async multi_tenant_enabled => {
        vi.mocked(getKnowledgeCapabilities).mockResolvedValue({
            platform_knowledge_enabled: true, platform_knowledge_mode: 'mock', platform_knowledge_connection_id: 'kunlian',
            platform_knowledge_policy_revision: 'v1', multi_tenant_enabled,
        });
        vi.mocked(listPlatformKnowledge).mockReset()
            .mockResolvedValueOnce({ items: [{ resource_id: 'mock:a', name: 'A', status: 'active', provider_mode: 'mock' }], next_cursor: null })
            .mockResolvedValueOnce({ items: [{ resource_id: 'mock:b', name: 'B', status: 'active', provider_mode: 'mock' }], next_cursor: null });
        const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
        function Harness({ tenant }: { tenant?: number }) {
            const defaults = useContext(userContext);
            return <userContext.Provider value={{ ...defaults, user: { user_id: 12, leaf_tenant_id: tenant } }}>
                <PlatformKnowledgeSelectItem workflowId="flow" reference={null} onChange={vi.fn()} onValidate={vi.fn()} />
            </userContext.Provider>;
        }
        const tree = (tenant?: number) => <QueryClientProvider client={queryClient}><Harness tenant={tenant} /></QueryClientProvider>;
        const view = render(tree(multi_tenant_enabled ? 7 : undefined));
        expect(await screen.findByRole('option', { name: 'A' })).toBeInTheDocument();
        view.rerender(tree(8));
        expect(await screen.findByRole('option', { name: 'B' })).toBeInTheDocument();
        expect(screen.queryByRole('option', { name: 'A' })).not.toBeInTheDocument();
    });

    it('invalidates a selection when refreshed details fail', async () => {
        vi.mocked(getKnowledgeCapabilities).mockResolvedValue({
            platform_knowledge_enabled: true, platform_knowledge_mode: 'mock', platform_knowledge_connection_id: 'kunlian',
            platform_knowledge_policy_revision: 'v1', multi_tenant_enabled: false,
        });
        vi.mocked(listPlatformKnowledge).mockResolvedValue({ items: [], next_cursor: null });
        vi.mocked(getPlatformKnowledge).mockReset()
            .mockResolvedValueOnce({ resource_id: 'mock:private', name: 'Private', status: 'active', provider_mode: 'mock' })
            .mockRejectedValue(new Error('access removed'));
        const queryClient = new QueryClient({ logger: { log: vi.fn(), warn: vi.fn(), error: vi.fn() } });
        const onValidate = vi.fn<(validate: () => string | false) => void>();
        function Harness() {
            const defaults = useContext(userContext);
            return <userContext.Provider value={{ ...defaults, user: { user_id: 12 } }}>
                <PlatformKnowledgeSelectItem workflowId="flow" reference={{ resource_id: 'mock:private' }}
                    onChange={vi.fn()} onValidate={onValidate} />
            </userContext.Provider>;
        }
        render(<QueryClientProvider client={queryClient}><Harness /></QueryClientProvider>);
        expect(await screen.findByRole('option', { name: 'Private' })).toBeInTheDocument();
        expect(onValidate.mock.lastCall?.[0]()).toBe(false);
        await act(async () => { await queryClient.refetchQueries({ queryKey: ['platform-knowledge'] }); });
        await waitFor(() => expect(onValidate.mock.lastCall?.[0]()).toBe('platformKnowledge.invalidKnowledge'));
        expect(screen.queryByRole('option', { name: 'Private' })).not.toBeInTheDocument();
    });

    it('distinguishes a directory permission denial from an empty directory', async () => {
        vi.mocked(getKnowledgeCapabilities).mockResolvedValue({
            platform_knowledge_enabled: true, platform_knowledge_mode: 'mock', platform_knowledge_connection_id: 'kunlian',
            platform_knowledge_policy_revision: 'v1', multi_tenant_enabled: false,
        });
        vi.mocked(listPlatformKnowledge).mockRejectedValue(new ApiError(null, {
            message: 'Denied', envelope: { status_code: 10564 },
        }));
        const queryClient = new QueryClient({ logger: { log: vi.fn(), warn: vi.fn(), error: vi.fn() } });
        function Harness() {
            const defaults = useContext(userContext);
            return <userContext.Provider value={{ ...defaults, user: { user_id: 12 } }}>
                <PlatformKnowledgeSelectItem workflowId="flow" reference={null} onChange={vi.fn()} onValidate={vi.fn()} />
            </userContext.Provider>;
        }
        render(<QueryClientProvider client={queryClient}><Harness /></QueryClientProvider>);
        expect(await screen.findByRole('alert')).toHaveTextContent('api_errors:10564');
        expect(screen.queryByText('platformKnowledge.empty')).not.toBeInTheDocument();
    });
});
