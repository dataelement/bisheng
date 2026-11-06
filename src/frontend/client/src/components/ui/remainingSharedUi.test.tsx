import { fireEvent, render, screen } from '@testing-library/react';
import { CommentDialog } from './CommentDialog';
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

  it.each(['pointer', 'keyboard'])('opens the preset chooser using %s', (method) => {
    render(<PresetsMenu />);
    const trigger = screen.getByRole('button', { name: 'com_endpoint_examples' });
    if (method === 'pointer') fireEvent.click(trigger);
    else fireEvent.keyDown(trigger, { key: 'Enter' });
    expect(screen.getByText('Preset choices')).toBeVisible();
  });

});
