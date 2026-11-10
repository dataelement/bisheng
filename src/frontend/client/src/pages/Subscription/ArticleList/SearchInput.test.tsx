import { fireEvent, render, screen } from '@testing-library/react';
import { SearchInput } from './SearchInput';

jest.mock('~/hooks', () => ({
  useLocalize: () => (key: string) => key,
  useMediaQuery: () => true,
}));
jest.mock('~/utils', () => ({ cn: (...parts: unknown[]) => parts.filter(Boolean).join(' ') }));

it.each([
  { fullWidth: false, expectedWidth: 'w-[220px]' },
  { fullWidth: true, expectedWidth: 'w-full' },
])('keeps the search editable in a compact viewport with fullWidth=$fullWidth', ({ fullWidth, expectedWidth }) => {
  const onChange = jest.fn();
  render(<SearchInput value="" onChange={onChange} fullWidth={fullWidth} />);

  const input = screen.getByRole('textbox');
  expect(input).toHaveAttribute('tabindex', '0');
  // jsdom cannot measure the Tailwind layout. The mobile row alone takes full width.
  expect(input.closest('[data-expandable-search]')).toHaveClass(expectedWidth, 'max-w-full');
  fireEvent.change(input, { target: { value: 'weekly' } });
  expect(onChange).toHaveBeenCalledWith('weekly');
});
