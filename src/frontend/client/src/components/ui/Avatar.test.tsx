import { fireEvent, render, screen } from '@testing-library/react';
import { UserAvatar } from './Avatar';

describe('UserAvatar', () => {
  it('renders the first Unicode character and falls back for blank names', () => {
    const initial = String.fromCodePoint(0x20bb7);
    const { rerender } = render(<UserAvatar name={`  ${initial}Jones`} />);
    expect(screen.getByText(initial)).toHaveClass('bg-fill-4', 'text-white');
    rerender(<UserAvatar name="alice" />);
    expect(screen.getByText('A')).toBeInTheDocument();
    rerender(<UserAvatar name="  " />);
    expect(screen.getByText('?')).toBeInTheDocument();
  });

  it('shows the initial after an image error and loads a new source', () => {
    const { rerender } = render(<UserAvatar name="Alice" alt="Alice" src="/old.png" />);
    fireEvent.error(screen.getByRole('img', { name: 'Alice' }));
    expect(screen.getByText('A')).toBeInTheDocument();

    rerender(<UserAvatar name="Alice" alt="Alice" src="/updated.png" />);
    expect(screen.getByRole('img', { name: 'Alice' })).toHaveAttribute('src', '/updated.png');
    expect(screen.queryByText('A')).not.toBeInTheDocument();
  });
});
