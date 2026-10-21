import { fireEvent, render, screen } from '@testing-library/react';
import { CommentDialog } from './CommentDialog';
import MultiSelect from './MultiSelect';
import PresetsMenu from '~/components/Chat/Menus/PresetsMenu';

jest.mock('~/hooks', () => ({
  useLocalize: () => (key: string) => key,
  usePresets: () => ({ presetsQuery: { data: [] } }),
}));

jest.mock('~/Providers', () => ({ useChatContext: () => ({ preset: undefined }) }));
jest.mock('~/components/Chat/Menus/Presets', () => ({
  PresetItems: () => <div>Preset choices</div>,
  EditPresetDialog: () => null,
}));

describe('shared controls at business boundaries', () => {
  it('blocks an over-limit comment and submits the corrected draft', () => {
    const submit = jest.fn();
    render(<CommentDialog open onOpenChange={jest.fn()} title="Feedback" onSubmit={submit} />);
    const field = screen.getByRole('textbox');
    fireEvent.change(field, { target: { value: 'x'.repeat(10000) } });
    expect(field).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByRole('button', { name: 'com_ui_submit' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'com_ui_submit' }));
    expect(submit).not.toHaveBeenCalled();
    fireEvent.change(field, { target: { value: '  Corrected  ' } });
    fireEvent.click(screen.getByRole('button', { name: 'com_ui_submit' }));
    expect(submit).toHaveBeenCalledWith('Corrected');
  });

  it('discards a comment draft when the dialog is reopened', () => {
    const props = { onOpenChange: jest.fn(), title: 'Feedback', onSubmit: jest.fn() };
    const { rerender } = render(<CommentDialog open {...props} />);
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Unsubmitted' } });
    rerender(<CommentDialog open={false} {...props} />);
    rerender(<CommentDialog open {...props} />);
    expect(screen.getByRole('textbox')).toHaveValue('');
  });

  it('removes an unlocked selected tag while retaining locked selections', () => {
    const change = jest.fn();
    render(<MultiSelect multiple value={['a', 'b']} lockedValues={['a']}
      options={[{ value: 'a', label: 'Locked' }, { value: 'b', label: 'Removable' }]}
      onChange={change} />);
    expect(screen.getByText('Locked')).toBeInTheDocument();
    expect(screen.getByText('Removable')).toBeInTheDocument();
    const remove = screen.getAllByRole('button', { name: 'com_ui_delete' });
    expect(remove).toHaveLength(1);
    fireEvent.click(remove[0]);
    expect(change).toHaveBeenLastCalledWith(['a']);
  });
  it('keeps every selected tag immutable while the selector is disabled', () => {
    const change = jest.fn();
    render(<MultiSelect multiple disabled value={['a']} options={[{ value: 'a', label: 'Selected' }]} onChange={change} />);
    const remove = screen.getByRole('button', { name: 'com_ui_delete' });
    expect(remove).toBeDisabled();
    fireEvent.click(remove);
    expect(change).not.toHaveBeenCalled();
    expect(screen.getByRole('combobox')).toHaveAttribute('aria-disabled', 'true');
  });

  it.each(['pointer', 'keyboard'])('opens the preset chooser using %s', (method) => {
    render(<PresetsMenu />);
    const trigger = screen.getByRole('button', { name: 'com_endpoint_examples' });
    if (method === 'pointer') fireEvent.click(trigger);
    else fireEvent.keyDown(trigger, { key: 'Enter' });
    expect(screen.getByText('Preset choices')).toBeVisible();
  });

});
