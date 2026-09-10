import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import MessageFeedback from '@/pages/LogPage/useAppLog/MessageFeedback';

afterEach(cleanup);

it('displays saved feedback as text even after rating was cancelled', () => {
    const comment = '<img src=x onerror=alert(1)>\n需要文档依据';
    const { container } = render(<MessageFeedback liked={0} comment={comment} />);
    expect(screen.getByText(/需要文档依据/)).toBeTruthy();
    expect(container.textContent).toContain('<img src=x onerror=alert(1)>');
    expect(container.querySelector('img')).toBeNull();
});

it('hides empty feedback and shows dislike independently of text', () => {
    const { container, rerender } = render(<MessageFeedback liked={0} comment="" />);
    expect(container.textContent).toBe('');
    rerender(<MessageFeedback liked={2} comment="" />);
    expect(container.textContent).not.toBe('');
});
