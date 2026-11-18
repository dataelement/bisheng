/**
 * F004 design §7 item 2: a tool call that was running when the user stopped
 * the run is shown as stopped, not as a failure.
 */
import { render, screen } from '@testing-library/react';
import type { AgentToolCall } from '~/api/chatApi';
import { STOPPED_TOOL_NOTE } from '~/hooks/unifiedRun';
import ToolCallDisplay from './ToolCallDisplay';

jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));
jest.mock('~/hooks/queries/data-provider', () => ({
    useGetBsConfig: () => ({ data: { unified_runtime_enabled: true } }),
}));
jest.mock('~/components/ChatErrorCard', () => ({ ChatErrorCard: () => null }));
jest.mock('~/components/Memory/MemorySearchHits', () => ({ MemorySearchHits: () => null }));

const call = (over: Partial<AgentToolCall> = {}): AgentToolCall => ({
    tool_call_id: 't1',
    tool_name: 'my_tool',
    tool_type: 'tool',
    inflight: false,
    ...over,
});

it('matches the note the backend stores', () => {
    expect(STOPPED_TOOL_NOTE).toBe('stopped by user');
});

it('shows a stopped call with the neutral label and no error text', () => {
    render(<ToolCallDisplay toolCall={call({ error: STOPPED_TOOL_NOTE })} />);
    expect(screen.getByText('runMessage.toolStopped')).toBeInTheDocument();
    expect(screen.getByTestId('tool-call-stopped')).toBeInTheDocument();
    expect(screen.queryByText('com_tools_state_tool_failed')).toBeNull();
    expect(screen.queryByText(STOPPED_TOOL_NOTE)).toBeNull();
});

it.each(['knowledge', 'web'])('does the same for a %s call', (toolType) => {
    render(<ToolCallDisplay toolCall={call({ tool_type: toolType, error: STOPPED_TOOL_NOTE })} />);
    expect(screen.getByText('runMessage.toolStopped')).toBeInTheDocument();
    expect(screen.queryByText(STOPPED_TOOL_NOTE)).toBeNull();
});

it('keeps the failed style for a real tool error', () => {
    render(<ToolCallDisplay toolCall={call({ error: 'timeout' })} />);
    expect(screen.getByText('com_tools_state_tool_failed')).toBeInTheDocument();
    expect(screen.getByText('timeout')).toBeInTheDocument();
    expect(screen.queryByTestId('tool-call-stopped')).toBeNull();
});
