import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import AuditFeedbackButton from '@/pages/LogPage/useAppLog/AuditFeedbackButton';

vi.mock('@/components/bs-icons/thumbs', () => ({ ThunmbIcon: () => <svg /> }));

afterEach(cleanup);

it('opens saved opinions directly from the feedback count and renders them as text', () => {
    const { container } = render(<AuditFeedbackButton count={2} comments={[
        { message_id: 321, liked: 0, comment: '<img src=x onerror=alert(1)>请补充出处' },
        { message_id: 322, liked: 2, comment: '历史意见' },
    ]} />);
    const button = screen.getByRole('button', { name: 'log.feedbackOpinions' });
    expect(button).toHaveTextContent('2');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    fireEvent.click(button);
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByText(/请补充出处/)).toBeInTheDocument();
    expect(within(dialog).getByText(/历史意见/)).toBeInTheDocument();
    expect(dialog.querySelector('img')).toBeNull();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Close' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(container).toHaveTextContent('2');
});

it('shows zero and an empty state when there are no saved opinions', () => {
    render(<AuditFeedbackButton count={0} comments={[]} />);
    const button = screen.getByRole('button', { name: 'log.feedbackOpinions' });
    expect(button).toHaveTextContent('0');
    fireEvent.click(button);
    expect(within(screen.getByRole('dialog')).getByText('log.noFeedback')).toBeInTheDocument();
});
