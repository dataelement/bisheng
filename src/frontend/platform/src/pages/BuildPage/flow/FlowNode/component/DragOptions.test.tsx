import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import DragOptions from './DragOptions';
import { StrictMode } from 'react';
import { installDragDimensions, keyboardDrag } from '@/test/keyboardDrag';
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
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

it('reorders in StrictMode and still allows editing the moved option', async () => {
    installDragDimensions();
    const onChange = vi.fn();
    render(<StrictMode><DragOptions edit options={[{ id: 'a', text: 'Again', type: '' }, { id: 'b', text: 'Stop', type: '' }]} onChange={onChange} /></StrictMode>);
    await keyboardDrag();
    expect(onChange).toHaveBeenLastCalledWith([{ id: 'b', text: 'Stop', type: '' }, { id: 'a', text: 'Again', type: '' }]);
    fireEvent.click(screen.getByTitle('Again').querySelector('svg.cursor-pointer')!);
    const input = screen.getByRole('textbox');
    fireEvent.change(input, { target: { value: 'Continue' } });
    fireEvent.blur(input);
    expect(onChange).toHaveBeenLastCalledWith([{ id: 'b', text: 'Stop', type: '' }, { id: 'a', text: 'Continue', type: '' }]);
});

it('does not save an order when a keyboard drag is cancelled', async () => {
    installDragDimensions();
    const onChange = vi.fn();
    render(<StrictMode><DragOptions options={[{ id: 'a', text: 'Again', type: '' }, { id: 'b', text: 'Stop', type: '' }]} onChange={onChange} /></StrictMode>);
    await keyboardDrag(0, true);
    expect(onChange).not.toHaveBeenCalled();
});

it('does not emit a save when dropped at the original position', async () => {
    installDragDimensions();
    const onChange = vi.fn();
    render(<StrictMode><DragOptions options={[{ id: 'a', text: 'Again', type: '' }, { id: 'b', text: 'Stop', type: '' }]} onChange={onChange} /></StrictMode>);
    await keyboardDrag(0, false, false);
    expect(onChange).not.toHaveBeenCalled();
});
