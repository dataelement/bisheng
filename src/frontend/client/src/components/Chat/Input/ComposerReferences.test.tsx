import { fireEvent, render, screen } from '@testing-library/react';
import { ComposerReferences } from './ComposerReferences';

// jsdom has no layout observer; behavior tests use deterministic geometry.
beforeAll(() => {
    global.ResizeObserver = class {
        observe() {}
        unobserve() {}
        disconnect() {}
    };
});

const skill = { name: 'office-docx', display_name: 'Word documents' };
const space = { id: 'space-1', type: 'knowledge', name: 'Product' };

test('references stay in the composer and can be removed independently with keyboard or pointer', () => {
    const removeSkill = jest.fn();
    const removeSpace = jest.fn();
    const focus = jest.fn();
    const props = { skills: [skill], spaces: [space], onRemoveSkill: removeSkill, onRemoveSpace: removeSpace, onFocusInput: focus };
    const view = render(<><textarea defaultValue="Draft remains" /><ComposerReferences {...props} /></>);
    fireEvent.click(screen.getByRole('button', { name: '/Word documents', exact: true }));
    expect(focus).toHaveBeenCalledTimes(1);
    expect(removeSkill).not.toHaveBeenCalled();
    fireEvent.keyDown(screen.getByRole('button', { name: '/Word documents', exact: true }), { key: 'Backspace' });
    expect(removeSkill).toHaveBeenCalledWith(skill);
    expect(removeSpace).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Remove @Product' }));
    expect(removeSpace).toHaveBeenCalledWith(space);
    expect(screen.getByRole('textbox')).toHaveValue('Draft remains');
    view.rerender(<><textarea defaultValue="Draft remains" /><ComposerReferences {...props} disabled /></>);
    expect(screen.getByRole('button', { name: 'Remove @Product' })).toBeDisabled();
});
