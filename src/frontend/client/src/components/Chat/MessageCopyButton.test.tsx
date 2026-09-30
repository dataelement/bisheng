/**
 * F072 AC-15 / AC-20: copying a daily chat answer drops [Sn] handles the
 * backend could not resolve (recognised ones are already hidden markers, which
 * copyText strips). Knowledge-space and channel docks do not opt in, so their
 * copy text keeps any bracketed text as written.
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { CopyButton } from './MessageCopyButton';

const mockCopyText = jest.fn();

jest.mock('~/utils', () => ({
    copyText: (text: string) => mockCopyText(text),
}));

jest.mock('~/hooks', () => ({
    useLocalize: () => (key: string) => key,
}));

jest.mock('bisheng-icons', () => ({
    Outlined: new Proxy(
        {},
        {
            get: () => () => null,
        },
    ),
}));

beforeEach(() => mockCopyText.mockReset());

test('daily chat copy drops unresolved handles and keeps other brackets', () => {
    render(<CopyButton text="Result. [S99] See note [3]." stripHandles />);
    fireEvent.click(screen.getByRole('button'));
    expect(mockCopyText).toHaveBeenCalledWith('Result.  See note [3].');
});

test('docks that do not opt in copy the text unchanged', () => {
    render(<CopyButton text="Result. [S99]" />);
    fireEvent.click(screen.getByRole('button'));
    expect(mockCopyText).toHaveBeenCalledWith('Result. [S99]');
});
