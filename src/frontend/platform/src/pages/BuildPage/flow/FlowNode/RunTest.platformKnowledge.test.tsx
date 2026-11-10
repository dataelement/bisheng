import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createRef, type ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { runWorkflowNodeApi } from '@/controllers/API/workflow';
import { RunTest } from './RunTest';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock('react-router-dom', () => ({ useParams: () => ({ id: 'flow' }) }));
vi.mock('@/components/bs-comp/formFields/useSelectLabels', () => ({ useSelectLabels: () => ({}) }));
vi.mock('@/components/bs-ui/sheet', () => {
    const box = ({ children }: { children: ReactNode }) => <div>{children}</div>;
    return { Sheet: box, SheetClose: box, SheetContent: box, SheetFooter: box, SheetHeader: box, SheetTitle: box };
});
vi.mock('./NodeLogo', () => ({ default: () => null }));
vi.mock('@/utils', () => ({ copyText: vi.fn() }));
vi.mock('@/controllers/request', () => ({ showApiError: vi.fn() }));
vi.mock('@/controllers/API/workflow', () => ({ runWorkflowNodeApi: vi.fn(), validatePlatformAgents: vi.fn() }));
vi.mock('@/controllers/API/platformKnowledge', () => ({ validatePlatformKnowledge: vi.fn().mockResolvedValue({ valid: true }) }));
vi.mock('../flowStore', () => ({
    default: Object.assign((select: (state: unknown) => unknown) => select({ runCache: {}, setRunCache: vi.fn() }), {
        getState: () => ({ flow: { nodes: [], edges: [] } }),
    }),
}));
vi.mock('@bisheng/ui', () => ({
    Button: 'button',
    Select: 'select',
    Textarea: ({ textareaClassName, ...props }: React.TextareaHTMLAttributes<HTMLTextAreaElement> & { textareaClassName: string }) =>
        <textarea {...props} className={textareaClassName} />,
    toast: { show: vi.fn() },
}));

describe('knowledge node trial', () => {
    it('sends the selected variable and clears output when the next trial fails', async () => {
        const handle = createRef<{ run: (node: unknown) => void }>();
        render(<RunTest ref={handle} />);
        const node = {
            type: 'platform_knowledge_retriever', id: 'search', name: 'Search',
            group_params: [{ params: [{
                key: 'user_question', type: 'platform_knowledge_query', value: { source: 'variable', variable: 'input.question' },
            }] }],
        };
        vi.mocked(runWorkflowNodeApi).mockResolvedValueOnce([[{ key: 'search.retrieved_text', value: 'matched', type: 'variable' }]])
            .mockRejectedValueOnce(new Error('fixture timeout'));
        act(() => handle.current?.run(node));
        fireEvent.change(screen.getByRole('textbox'), { target: { value: 'question' } });
        fireEvent.click(screen.getByRole('button', { name: 'run' }));
        expect(await screen.findByDisplayValue('matched')).toBeInTheDocument();
        expect(runWorkflowNodeApi).toHaveBeenCalledWith({ node_input: { 'input.question': 'question' }, data: node, workflow_id: 'flow' });
        fireEvent.click(screen.getByRole('button', { name: 'run' }));
        await waitFor(() => expect(runWorkflowNodeApi).toHaveBeenCalledTimes(2));
        expect(screen.queryByDisplayValue('matched')).not.toBeInTheDocument();
    });
});
