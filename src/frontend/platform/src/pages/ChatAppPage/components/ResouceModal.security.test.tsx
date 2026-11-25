import { cleanup, fireEvent, render, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { ResouceContent } from './ResouceModal';

const api = vi.hoisted(() => ({ split: vi.fn(), chunks: vi.fn().mockResolvedValue([]) }));
vi.mock('../../../controllers/API', () => ({ splitWordApi: api.split, getSourceChunksApi: api.chunks }));
vi.mock('./FileViewPanne', () => ({ default: () => null }));
vi.mock('@/components/bs-comp/FileView', () => ({ checkSassUrl: (value: string) => value }));
vi.mock('../../../util/utils', () => ({ downloadFile: vi.fn() }));
vi.mock('@bisheng/ui', () => ({ Input: 'input', Button: 'button', Tag: 'span', Tooltip: 'div', TooltipProvider: 'div' }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });

it('renders untrusted answer HTML as text while keeping only generated keyword spans', async () => {
    const answer = 'safe <img src=x onerror="syntheticCanary()"> <a href="javascript:SYNTHETIC">link</a> <svg onload="syntheticCanary()">';
    api.split.mockResolvedValue(['safe', '<img']);
    const { container } = render(<ResouceContent data={{ message: answer, messageId: 'm1', chatId: 'c1' }} setOpen={vi.fn()} />);
    await waitFor(() => expect(container.querySelector('.anwser-souce')?.textContent).toBe(answer));
    const source = container.querySelector('.anwser-souce')!;
    expect(source.querySelector('img, a, svg, script, iframe')).toBeNull();
    expect([...source.querySelectorAll('span')].map(span => span.textContent)).toEqual(['safe', '<img']);
    fireEvent.click(source.querySelector('span')!);
});

it('treats regex syntax and replacement metacharacters in keywords literally', async () => {
    const answer = 'a+b [tag] $& a+b';
    api.split.mockResolvedValue(['a+b', '[tag]', '$&', '', 'a+b']);
    const { container } = render(<ResouceContent data={{ message: answer, messageId: 'm2', chatId: 'c1' }} setOpen={vi.fn()} />);
    await waitFor(() => expect(container.querySelector('.anwser-souce')?.textContent).toBe(answer));
    expect([...container.querySelectorAll('.anwser-souce span')].map(span => span.textContent)).toEqual(['a+b', '[tag]', '$&', 'a+b']);
});
