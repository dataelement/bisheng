import React from 'react';
import { render } from '@testing-library/react';
import { AvatarName } from './Avatar';

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
