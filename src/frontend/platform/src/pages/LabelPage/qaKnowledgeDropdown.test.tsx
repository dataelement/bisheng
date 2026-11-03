import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createRef } from 'react';
import { QueryClientProvider } from '@tanstack/react-query';
import { createPlatformQueryClient } from '@/queryClient';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import SaveQaLibForm from './SaveQaLibForm';
import AddSimilarQuestions from './AddSimilarQuestions';
import type { AnnotationFormHandle } from './annotationTypes';

const api = vi.hoisted(() => ({ read: vi.fn(), update: vi.fn(), list: vi.fn() }));
vi.mock('@/controllers/API', () => ({
    readFileLibDatabase: api.read, updateQa: api.update, getQaList: api.list,
    addSimilarQa: vi.fn(), generateSimilarQa: vi.fn(),
}));
const longName = 'Long QA name '.repeat(60).trim();
beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(360);
    api.read.mockResolvedValue({ data: [{ id: 'qa-1', name: longName }, { id: 'qa-2', name: 'Other QA' }], next_cursor: null });
    api.update.mockResolvedValue({});
    api.list.mockResolvedValue({ data: [], total: 0 });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

function mount(Component = SaveQaLibForm) {
    const ref = createRef<AnnotationFormHandle>();
    render(<QueryClientProvider client={createPlatformQueryClient()}><Component ref={ref} /></QueryClientProvider>);
    act(() => ref.current?.open('message', { q: 'Question', a: 'Answer' }));
}

it.each([['new QA', SaveQaLibForm], ['similar questions', AddSimilarQuestions]] as const)(
    '%s uses a trigger-width panel and truncates long library names', async (_name, Component) => {
        mount(Component);
        fireEvent.click(screen.getByRole('combobox', { name: 'log.qaKnowledgeLib' }));
        const option = await screen.findByRole('option', { name: longName });
        expect(option.closest('[data-side]')).toHaveClass('w-[var(--radix-popover-trigger-width)]');
        expect(screen.getByText(longName)).toHaveClass('truncate');
    },
);

it('replaces the selected QA library rather than accumulating a second selection', async () => {
    mount();
    const select = screen.getByRole('combobox', { name: 'log.qaKnowledgeLib' });
    fireEvent.click(select);
    fireEvent.click(await screen.findByRole('option', { name: longName }));
    expect(screen.queryByRole('listbox')).toBeNull();
    fireEvent.click(select);
    fireEvent.click(await screen.findByRole('option', { name: 'Other QA' }));
    fireEvent.click(screen.getByRole('button', { name: 'log.confirm' }));
    await waitFor(() => expect(api.update).toHaveBeenCalledWith('', expect.objectContaining({ knowledge_id: 'qa-2' })));
});
