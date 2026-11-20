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

describe('generic tool row: view code and output (AC-25)', () => {
    it('opens the code and the output, then collapses', () => {
        render(<ToolCallDisplay toolCall={call()} />);
        expect(screen.queryByText('print(1 + 1)')).toBeNull();
        fireEvent.click(screen.getByText('runTool.viewCodeOutput'));
        expect(screen.getByText('runTool.code')).toBeInTheDocument();
        expect(screen.getByText('print(1 + 1)')).toBeInTheDocument();
        expect(screen.getByText('runTool.output')).toBeInTheDocument();
        expect(screen.getByText('2')).toBeInTheDocument();
        fireEvent.click(screen.getByText('runTool.collapse'));
        expect(screen.queryByText('print(1 + 1)')).toBeNull();
    });
    it('shows all parameters when the call carries no code', () => {
        render(<ToolCallDisplay toolCall={call({ tool_name: 'weather', args: { city: 'Taipei' }, results: { temp: 21 } })} />);
        fireEvent.click(screen.getByText('runTool.viewCodeOutput'));
        expect(screen.getByText('runTool.params')).toBeInTheDocument();
        expect(screen.getByText(/"city": "Taipei"/)).toBeInTheDocument();
        expect(screen.getByText(/"temp": 21/)).toBeInTheDocument();
    });
    it('is absent while the call runs, after it failed, and when it has nothing to show', () => {
        const { rerender } = render(<ToolCallDisplay toolCall={call({ inflight: true })} />);
        expect(screen.queryByText('runTool.viewCodeOutput')).toBeNull();
        rerender(<ToolCallDisplay toolCall={call({ error: 'boom' })} />);
        expect(screen.queryByText('runTool.viewCodeOutput')).toBeNull();
        rerender(<ToolCallDisplay toolCall={call({ args: undefined, results: undefined })} />);
        expect(screen.queryByText('runTool.viewCodeOutput')).toBeNull();
    });
    it('is absent on knowledge and web rows', () => {
        render(<ToolCallDisplay toolCall={call({ tool_name: 'web_search', tool_type: 'web', results: [] })} />);
        expect(screen.queryByText('runTool.viewCodeOutput')).toBeNull();
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
