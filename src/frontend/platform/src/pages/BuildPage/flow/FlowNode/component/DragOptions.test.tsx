import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import DragOptions from './DragOptions';
afterEach(cleanup);
function setup() {
    const onChange = vi.fn();
    render(<DragOptions edit options={[{ id: 'option-a', text: 'Again', type: '' }, { id: 'option-b', text: 'Stop', type: '' }]} onChange={onChange} />);
    const editIcon = screen.getByTitle('Again').querySelector('svg.cursor-pointer');
    expect(editIcon).not.toBeNull();
    fireEvent.click(editIcon!);
    return { onChange, input: screen.getByRole('textbox') };
}
it('allows continued typing and commits the edited label on blur without changing the option identity', () => {
    const { input, onChange } = setup();
    fireEvent.change(input, { target: { value: 'Again one' } });
    expect(input).toHaveValue('Again one');
    fireEvent.change(input, { target: { value: 'Again one more' } });
    expect(input).toHaveValue('Again one more');
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.blur(input);
    expect(onChange).toHaveBeenCalledWith([{ id: 'option-a', text: 'Again one more', type: '' }, { id: 'option-b', text: 'Stop', type: '' }]);
    expect(screen.queryByRole('textbox')).toBeNull();
});
it('commits the edited option on Enter', () => {
    const { input, onChange } = setup();
    fireEvent.change(input, { target: { value: 'Continue' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onChange).toHaveBeenCalledWith(expect.arrayContaining([{ id: 'option-a', text: 'Continue', type: '' }]));
});
it('does not finish editing when Enter confirms an IME composition', () => {
    const { input, onChange } = setup();
    fireEvent.keyDown(input, { key: 'Enter', isComposing: true });
    expect(screen.getByRole('textbox')).toBe(input);
    expect(onChange).not.toHaveBeenCalled();
});
