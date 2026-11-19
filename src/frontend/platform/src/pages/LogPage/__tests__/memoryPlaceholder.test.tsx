import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { PlatformConversationMessages } from '@/components/bs-comp/appChat/PlatformConversationMessages';
import DailyChatDetail from '../useAppLog/dailyChatDetail';
import zhHans from '../../../../public/locales/zh-Hans/bs.json';
import enUS from '../../../../public/locales/en-US/bs.json';
import ja from '../../../../public/locales/ja/bs.json';

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn(), rows: [] as unknown[] }));

vi.mock('@/controllers/request', () => ({
    default: { get: mocks.get, post: mocks.post, put: mocks.put, delete: mocks.del },
    handleUiRequest: (handler: () => unknown) => handler,
    showApiError: vi.fn(),
}));
vi.mock('@/contexts/locationContext', async () => {
    const { createContext } = await import('react');
    return { locationContext: createContext({ appConfig: {} }) };
});
vi.mock('@/components/bs-comp/appChat/PlatformChatMarkdown', () => ({ PlatformChatMarkdown: ({ content }: { content: string }) => <div>{content}</div> }));
vi.mock('@/components/bs-comp/appChat/PlatformVoiceAction', () => ({ PlatformVoiceAction: () => null }));
vi.mock('@/components/bs-comp/chatComponent/CitationReferencesDrawer', () => ({ default: () => null }));
vi.mock('@/components/bs-comp/chatComponent/SourceEntry', () => ({ default: () => null }));
vi.mock('@/pages/ChatAppPage/components/ResouceModal', async () => {
    const { forwardRef } = await import('react');
    return { default: forwardRef(() => null) };
});
vi.mock('../useAppLog/DailyMessageContent', () => ({ MessageContent: ({ text }: { text: string }) => <div data-testid="daily-text">{text}</div> }));

const SECRET = 'User likes spicy noodles';
const redacted = { redacted: true, op: 'search', item_ids: ['m1'] };

function memoryRequests() {
    return [mocks.get, mocks.post, mocks.put, mocks.del].flatMap(fn => fn.mock.calls).filter(call => String(call[0]).includes('/api/v1/memory'));
}

beforeEach(() => {
    vi.clearAllMocks();
    globalThis.fetch = vi.fn() as unknown as typeof fetch;
    mocks.get.mockImplementation(async () => mocks.rows);
});
afterEach(cleanup);

describe('assistant and workflow log page', () => {
    function renderRows(rows: unknown[]) {
        return render(<PlatformConversationMessages mode="assistant" sessionKey="chat-1" messages={rows}
            canExecute={false} canAnnotate={false} runCatalog={{ tool_list: [{ tool_key: 'web_search', name: 'Web search' }] }} />);
    }

    it('AC-09: a redacted memory tool event renders only the placeholder', async () => {
        renderRows([
            { id: 1, category: 'question', is_bot: false, message: 'What do I like?' },
            { id: 2, category: 'tool', is_bot: true, message: JSON.stringify({ tool_key: 'memory_search', input_str: redacted, output: redacted }), intermediate_steps: `Tool input: ${JSON.stringify(redacted)}` },
            { id: 3, category: 'answer', is_bot: true, message: 'You like noodles.' },
        ]);
        expect(screen.getAllByText('memory.operation').length).toBeGreaterThanOrEqual(2);
        expect(screen.queryByText(/redacted|item_ids|m1/)).toBeNull();
        expect(screen.queryByText(/toolDeleted/)).toBeNull();
        expect(screen.getByText('You like noodles.')).toBeInTheDocument();
        expect(memoryRequests()).toEqual([]);
        expect(globalThis.fetch).not.toHaveBeenCalled();
    });

    it('AC-09: a memory tool row whose steps still carry item text never shows that text', () => {
        renderRows([
            { id: 2, category: 'tool', is_bot: true, message: JSON.stringify({ tool_key: 'memory_write', input_str: { content: SECRET }, output: 'ok' }), intermediate_steps: `Tool input: ${SECRET}` },
        ]);
        expect(screen.queryByText(new RegExp(SECRET))).toBeNull();
        expect(screen.getAllByText('memory.operation').length).toBeGreaterThanOrEqual(1);
    });

    it('AC-09: ordinary tool cards are unchanged', () => {
        renderRows([
            { id: 2, category: 'tool', is_bot: true, message: JSON.stringify({ tool_key: 'web_search', input_str: 'weather', output: 'sunny' }), intermediate_steps: 'Tool output: sunny' },
        ]);
        expect(screen.queryByText('memory.operation')).toBeNull();
        expect(screen.getByText('Tool output: sunny')).toBeInTheDocument();
    });
});

describe('daily chat log page', () => {
    function renderDaily() {
        return render(<MemoryRouter initialEntries={['/log/chat/c1']}><Routes><Route path="/log/chat/:cid" element={<DailyChatDetail />} /></Routes></MemoryRouter>);
    }
    const question = { messageId: 'q', isCreatedByUser: true, user_name: 'alice', sender: 'alice', text: JSON.stringify({ query: 'Remember me' }) };

    it('AC-09: an answer with only a memory tool event shows the placeholder, not the raw JSON', async () => {
        mocks.rows = [question, {
            messageId: 'a', isCreatedByUser: false, user_name: 'alice', sender: 'AI',
            text: JSON.stringify({ msg: '', events: [{ type: 'tool_call', tool_name: 'memory_write', args: redacted, results: redacted }] }),
        }];
        renderDaily();
        await waitFor(() => expect(screen.getAllByTestId('daily-text')).toHaveLength(2));
        const texts = screen.getAllByTestId('daily-text').map(node => node.textContent);
        expect(texts).toEqual(['Remember me', 'memory.operation']);
        expect(memoryRequests()).toEqual([]);
        expect(globalThis.fetch).not.toHaveBeenCalled();
    });

    it('AC-09: an answer with text shows only the answer body even when the event is not redacted', async () => {
        mocks.rows = [{
            messageId: 'a', isCreatedByUser: false, user_name: 'alice', sender: 'AI',
            text: JSON.stringify({ msg: 'Noted.', events: [{ type: 'tool_call', tool_name: 'memory_search', args: { query: SECRET }, results: [SECRET] }] }),
        }];
        renderDaily();
        await waitFor(() => expect(screen.getByTestId('daily-text')).toHaveTextContent('Noted.'));
        expect(screen.queryByText(new RegExp(SECRET))).toBeNull();
    });

    it('AC-09: an empty answer with an unredacted memory event still hides it', async () => {
        mocks.rows = [{
            messageId: 'a', isCreatedByUser: false, user_name: 'alice', sender: 'AI',
            text: JSON.stringify({ msg: '', events: [{ type: 'tool_call', tool_name: 'memory_search', args: { query: SECRET }, results: [SECRET] }] }),
        }];
        renderDaily();
        await waitFor(() => expect(screen.getByTestId('daily-text')).toHaveTextContent('memory.operation'));
        expect(screen.queryByText(new RegExp(SECRET))).toBeNull();
    });

    it('AC-09: the placeholder copy exists in all three languages', () => {
        for (const locale of [zhHans, enUS, ja]) expect(locale.memory.operation.length).toBeGreaterThan(0);
    });
});
