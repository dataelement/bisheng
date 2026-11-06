/* eslint-disable no-restricted-syntax -- CJK fixtures verify composition and display width. */
import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it } from 'vitest';
import { FormInput } from './FormInput';
import { isMenuNameTooLong } from './menuDisplayName';

function Field() {
    const [value, setValue] = useState('');
    return <FormInput label="Menu" value={value} error="" onChange={setValue}
        validate={(name) => isMenuNameTooLong(name) ? 'Name is too long' : ''} />;
}

describe('menu name input', () => {
    it('keeps the complete value and validates after Chinese composition ends', () => {
        render(<Field />);
        const input = screen.getByRole('textbox', { name: 'Menu' });
        fireEvent.compositionStart(input);
        fireEvent.change(input, { target: { value: 'zhishikongjian' } });
        expect(input).toHaveValue('zhishikongjian');
        expect(screen.queryByText('Name is too long')).not.toBeInTheDocument();
        fireEvent.change(input, { target: { value: '知识空间' } });
        fireEvent.compositionEnd(input);
        expect(input).toHaveValue('知识空间');
        expect(screen.queryByText('Name is too long')).not.toBeInTheDocument();
    });

    it('shows an error without truncation after composition and clears it when corrected', () => {
        render(<Field />);
        const input = screen.getByRole('textbox', { name: 'Menu' });
        fireEvent.compositionStart(input);
        fireEvent.change(input, { target: { value: '我的知识空间' } });
        fireEvent.compositionEnd(input);
        expect(input).toHaveValue('我的知识空间');
        expect(screen.getByText('Name is too long')).toBeInTheDocument();
        fireEvent.change(input, { target: { value: '知识空间' } });
        expect(screen.queryByText('Name is too long')).not.toBeInTheDocument();
    });

    it('preserves pasted text and accepts exactly four full-width or eight half-width characters', () => {
        render(<Field />);
        const input = screen.getByRole('textbox', { name: 'Menu' });
        fireEvent.change(input, { target: { value: '123456789' } });
        expect(input).toHaveValue('123456789');
        expect(screen.getByText('Name is too long')).toBeInTheDocument();
        expect(isMenuNameTooLong('知识空间')).toBe(false);
        expect(isMenuNameTooLong('12345678')).toBe(false);
        expect(isMenuNameTooLong('知识abcde')).toBe(true);
        expect(isMenuNameTooLong('')).toBe(false);
    });
});
