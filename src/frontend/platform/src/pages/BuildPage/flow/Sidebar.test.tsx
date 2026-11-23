import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import zhFlow from '../../../../public/locales/zh-Hans/flow.json';
import enFlow from '../../../../public/locales/en-US/flow.json';
import jaFlow from '../../../../public/locales/ja/flow.json';
import { getKnowledgeCapabilities } from '@/controllers/API/platformKnowledge';
import { getPlatformModelCapabilities } from '@/controllers/API/platformModel';
import { getToolsApi } from '@/controllers/API/tools';
import { getPlatformAgentCapabilities, getWorkflowNodeTemplate } from '@/controllers/API/workflow';
import Sidebar from './Sidebar';

const lookup = (obj: Record<string, any>, key: string) =>
    key.split('.').reduce<any>((acc, part) => (acc && typeof acc === 'object' ? acc[part] : undefined), obj);

vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        t: (key: string, opts?: { defaultValue?: string }) => lookup(zhFlow, key) ?? opts?.defaultValue ?? key,
    }),
}));

vi.mock('@bisheng/ui', () => ({
    Button: ({ children, iconOnly: _iconOnly, ...props }: any) => <button {...props}>{children}</button>,
    Tabs: ({ items }: any) => (
        <div>
            {items?.map((item: any) => (
                <span key={item.key}>{item.label}</span>
            ))}
        </div>
    ),
    Tooltip: ({ children }: any) => <>{children}</>,
}));

vi.mock('@/components/bs-ui/accordion', () => ({
    Accordion: ({ children }: any) => <div>{children}</div>,
    AccordionContent: ({ children }: any) => <div>{children}</div>,
    AccordionItem: ({ children }: any) => <div>{children}</div>,
    AccordionTrigger: ({ children }: any) => <div>{children}</div>,
}));

vi.mock('./FlowNode/NodeLogo', () => ({
    default: ({ type }: { type: string }) => <span data-testid={`node-logo-${type}`} />,
}));

vi.mock('@/controllers/API/tools', () => ({
    getToolsApi: vi.fn(),
}));

vi.mock('@/controllers/API/workflow', () => ({
    getWorkflowNodeTemplate: vi.fn(),
    getPlatformAgentCapabilities: vi.fn(),
}));

vi.mock('@/controllers/API/platformKnowledge', () => ({
    getKnowledgeCapabilities: vi.fn(),
}));

vi.mock('@/controllers/API/platformModel', () => ({
    getPlatformModelCapabilities: vi.fn(),
}));

function renderSidebar() {
    const queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false } },
    });
    return render(
        <QueryClientProvider client={queryClient}>
            <Sidebar />
        </QueryClientProvider>,
    );
}

describe('Sidebar workflow node visibility and naming', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        vi.mocked(getToolsApi).mockResolvedValue([]);
        vi.mocked(getWorkflowNodeTemplate).mockResolvedValue([
            { type: 'start' },
            { type: 'input' },
            { type: 'llm' },
            { type: 'qa_retriever' },
            { type: 'rag' },
            { type: 'knowledge_retriever' },
            { type: 'platform_agent' },
            { type: 'platform_knowledge_retriever' },
            { type: 'platform_llm' },
        ]);
    });

    it('hides original knowledge_retriever and llm and shows renamed platform nodes when enabled', async () => {
        vi.mocked(getPlatformAgentCapabilities).mockResolvedValue({
            platform_agent_enabled: true,
            platform_agent_mode: 'real',
            platform_agent_policy_revision: 'real-v1',
        });
        vi.mocked(getKnowledgeCapabilities).mockResolvedValue({
            platform_knowledge_enabled: true,
            platform_knowledge_mode: 'real',
            platform_knowledge_connection_id: 'kunlian',
        });
        vi.mocked(getPlatformModelCapabilities).mockResolvedValue({
            platform_llm_enabled: true,
        });

        renderSidebar();

        expect(await screen.findByTestId('node-logo-platform_knowledge_retriever')).toBeInTheDocument();
        expect(screen.getByTestId('node-logo-platform_llm')).toBeInTheDocument();
        expect(screen.queryByTestId('node-logo-knowledge_retriever')).not.toBeInTheDocument();
        expect(screen.queryByTestId('node-logo-llm')).not.toBeInTheDocument();
        expect(screen.getByTestId('node-logo-rag')).toBeInTheDocument();
        expect(screen.getByTestId('node-logo-qa_retriever')).toBeInTheDocument();
        expect(screen.getByText('知识库检索')).toBeInTheDocument();
        expect(screen.getByText('大模型')).toBeInTheDocument();
    });

    it('keeps original knowledge_retriever and llm when platform capabilities are disabled', async () => {
        vi.mocked(getPlatformAgentCapabilities).mockResolvedValue({
            platform_agent_enabled: false,
            platform_agent_mode: 'disabled',
            platform_agent_policy_revision: '',
        });
        vi.mocked(getKnowledgeCapabilities).mockResolvedValue({
            platform_knowledge_enabled: false,
            platform_knowledge_mode: 'disabled',
            platform_knowledge_connection_id: '',
        });
        vi.mocked(getPlatformModelCapabilities).mockResolvedValue({
            platform_llm_enabled: false,
        });

        renderSidebar();

        expect(await screen.findByTestId('node-logo-knowledge_retriever')).toBeInTheDocument();
        expect(screen.getByTestId('node-logo-llm')).toBeInTheDocument();
        expect(screen.queryByTestId('node-logo-platform_knowledge_retriever')).not.toBeInTheDocument();
        expect(screen.queryByTestId('node-logo-platform_llm')).not.toBeInTheDocument();
    });

    it('renames platform knowledge and llm strings across all three locale files', () => {
        for (const flowJson of [zhFlow, enFlow, jaFlow]) {
            expect(flowJson.node.platform_knowledge_retriever.name).not.toMatch(/昆联|Kunlian|昆聯/);
            expect(flowJson.node.platform_knowledge_retriever.description).not.toMatch(/昆联|Kunlian|昆聯/);
            expect(flowJson.node.platform_llm.name).not.toMatch(/昆联|Kunlian|昆聯/);
            expect(flowJson.node.platform_llm.description).not.toMatch(/昆联|Kunlian|昆聯/);
            expect(flowJson.node.platform_llm.model_ref.label).not.toMatch(/昆联|Kunlian|昆聯/);
            expect(flowJson.platformLlm.choose).not.toMatch(/昆联|Kunlian|昆聯/);
            expect(flowJson.platformLlm.invalidModel).not.toMatch(/昆联|Kunlian|昆聯/);
            expect(flowJson.platformLlm.tokenInvalid).toMatch(/昆联|Kunlian|昆聯/);
            expect(flowJson.platformLlm.permissionDenied).toMatch(/昆联|Kunlian|昆聯/);
        }
    });
});
