import { fireEvent, render, screen } from '@testing-library/react';
import { AvatarName, UserAvatar } from './Avatar';

describe('UserAvatar', () => {
  it('renders the first Unicode character and falls back for blank names', () => {
    const initial = String.fromCodePoint(0x20bb7);
    const { rerender } = render(<UserAvatar name={`  ${initial}Jones`} />);
    expect(screen.getByText(initial)).toHaveClass('bg-fill-4', 'text-white');
    rerender(<UserAvatar name="alice" />);
    expect(screen.getByText('A')).toBeInTheDocument();
    rerender(<UserAvatar name="  " />);
    expect(screen.queryByText('?')).not.toBeInTheDocument();
    expect(document.querySelector('svg')).not.toBeNull();
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

describe('AvatarName', () => {
  it('shows the first code point of the name, upper-cased', () => {
    const { container } = render(<AvatarName name="  alice" />);
    expect(container.textContent).toBe('A');
    expect(container.querySelector('svg')).toBeNull();
  });

  it('keeps a supplementary CJK character whole', () => {
    // U+20BB7 is outside the BMP: a UTF-16 index would split its surrogate pair.
    const { container } = render(<AvatarName name={'\u{20BB7}x'} />);
    expect(container.textContent).toBe('\u{20BB7}');
  });

  it.each([undefined, '', '   '])('shows a person icon instead of "?" when the name is %p', (name) => {
    const { container } = render(<AvatarName name={name} />);
    expect(container.textContent).toBe('');
    expect(container.querySelector('svg')).not.toBeNull();
  });
});
