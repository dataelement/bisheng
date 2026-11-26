import { fireEvent, render, screen } from '@testing-library/react';
import type { AgentToolCall } from '~/api/chatApi';
import ToolCallDisplay from './ToolCallDisplay';
import { toolCallInputText, toolCallOutputText } from './ToolCodeOutput';

jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));
jest.mock('~/components/ChatErrorCard', () => ({ ChatErrorCard: () => null }));
jest.mock('~/components/Memory/MemorySearchHits', () => ({ MemorySearchHits: () => null }));

const call = (over: Partial<AgentToolCall> = {}): AgentToolCall => ({
    tool_call_id: 't1',
    tool_name: 'bisheng_code_interpreter',
    tool_type: 'tool',
    args: { python_code: 'print(1 + 1)' },
    results: '2',
    inflight: false,
    ...over,
});

const row = () => screen.getByText('com_tools_state_tool_done').closest('button') as HTMLButtonElement;

describe('generic tool row: clicking the row shows code and output (AC-25)', () => {
    it('opens the code and the output, then collapses', () => {
        render(<ToolCallDisplay toolCall={call()} />);
        expect(screen.queryByText('print(1 + 1)')).toBeNull();
        expect(row()).not.toBeDisabled();
        fireEvent.click(row());
        expect(screen.getByText('runTool.code')).toBeInTheDocument();
        expect(screen.getByText('print(1 + 1)')).toBeInTheDocument();
        expect(screen.getByText('runTool.output')).toBeInTheDocument();
        expect(screen.getByText('2')).toBeInTheDocument();
        fireEvent.click(row());
        expect(screen.queryByText('print(1 + 1)')).toBeNull();
    });
    it('shows all parameters when the call carries no code', () => {
        render(<ToolCallDisplay toolCall={call({ tool_name: 'weather', args: { city: 'Taipei' }, results: { temp: 21 } })} />);
        fireEvent.click(row());
        expect(screen.getByText('runTool.params')).toBeInTheDocument();
        expect(screen.getByText(/"city": "Taipei"/)).toBeInTheDocument();
        expect(screen.getByText(/"temp": 21/)).toBeInTheDocument();
    });
    it('has no separate link', () => {
        render(<ToolCallDisplay toolCall={call()} />);
        expect(screen.getAllByRole('button')).toHaveLength(1);
    });
    it('does not expand while the call runs or when it has nothing to show', () => {
        const { rerender } = render(<ToolCallDisplay toolCall={call({ inflight: true })} />);
        expect(screen.queryByText('runTool.code')).toBeNull();
        rerender(<ToolCallDisplay toolCall={call({ args: undefined, results: undefined })} />);
        expect(row()).toBeDisabled();
    });
    it('a failed call shows its error, not code and output', () => {
        render(<ToolCallDisplay toolCall={call({ error: 'boom' })} />);
        expect(screen.getByText('boom')).toBeInTheDocument();
        expect(screen.queryByText('runTool.code')).toBeNull();
    });
});

describe('text helpers', () => {
    it('prefers the code string over the full parameter object', () => {
        expect(toolCallInputText({ code: 'ls', lang: 'sh' })).toEqual({ text: 'ls', isCode: true });
        expect(toolCallInputText({})).toEqual({ text: '', isCode: false });
        expect(toolCallInputText(undefined)).toEqual({ text: '', isCode: false });
    });
    it('renders any output as text', () => {
        expect(toolCallOutputText(' ok \n')).toBe('ok');
        expect(toolCallOutputText(null)).toBe('');
        expect(toolCallOutputText([1])).toBe('[\n  1\n]');
    });
});
