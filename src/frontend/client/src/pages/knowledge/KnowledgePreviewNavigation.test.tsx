import { fireEvent, render, screen } from '@testing-library/react';
import { KnowledgePreviewNavigation } from './KnowledgePreviewNavigation';

let mockEmbedded = true;
let mockMobile = false;
jest.mock('~/components/Chat/desktopEmbedding', () => ({ isDesktopEmbedded: () => mockEmbedded }));
jest.mock('~/hooks', () => ({
    useLocalize: () => (key: string) => key,
    usePrefersMobileLayout: () => mockMobile,
}));

it.each([false, true])('provides a labeled desktop return action with narrow layout=%s', mobile => {
    mockEmbedded = true;
    mockMobile = mobile;
    const close = jest.fn();
    render(<KnowledgePreviewNavigation onClose={close} />);
    const back = screen.getByRole('button', { name: 'com_ui_go_back' });
    expect(back).toBeVisible();
    fireEvent.click(back);
    expect(close).toHaveBeenCalledTimes(1);
});

it.each([
    [false, 'com_knowledge.collapse_drawer'],
    [true, 'com_knowledge.close'],
] as const)('preserves the browser close action with mobile=%s', (mobile, label) => {
    mockEmbedded = false;
    mockMobile = mobile;
    const close = jest.fn();
    render(<KnowledgePreviewNavigation onClose={close} />);
    fireEvent.click(screen.getByRole('button', { name: label }));
    expect(close).toHaveBeenCalledTimes(1);
});
