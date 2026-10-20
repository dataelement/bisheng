import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { ComposerReferences } from './ComposerReferences';
import { ContextResourceCard } from './ContextResourceCard';
import { handleComposerResourceKeyDown } from './composerResourceKeyboard';

beforeAll(() => {
    global.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
});
function Composer({ disabled = false, composing = false }) {
    const [skills, setSkills] = useState([{ name: 'word' }, { name: 'excel' }]);
    const [files, setFiles] = useState(['notes.txt']);
    return <div onKeyDownCapture={(event) => handleComposerResourceKeyDown(event, disabled, composing)}>
        {files.map((name) => <ContextResourceCard key={name} label={name} icon={null}
            onRemove={disabled ? undefined : () => setFiles(files.filter((file) => file !== name))} />)}
        <ComposerReferences skills={skills} spaces={[]} disabled={disabled}
            onRemoveSkill={(skill) => setSkills(skills.filter((item) => item.name !== skill.name))}
            onRemoveSpace={() => {}} onFocusInput={() => screen.getByRole('textbox').focus()} />
        <textarea defaultValue="draft" />
    </div>;
}

test('backspace at the start removes references then files in visual order and preserves text', () => {
    render(<Composer />);
    const input = screen.getByRole('textbox') as HTMLTextAreaElement;
    input.focus(); input.setSelectionRange(0, 0);
    fireEvent.keyDown(input, { key: 'Backspace' });
    expect(screen.queryByRole('button', { name: '/excel', exact: true })).toBeNull();
    expect(screen.getByRole('button', { name: '/word', exact: true })).toBeInTheDocument();
    fireEvent.keyDown(input, { key: 'Backspace' });
    expect(screen.queryByRole('button', { name: '/word', exact: true })).toBeNull();
    fireEvent.keyDown(input, { key: 'Backspace' });
    expect(screen.queryByText('notes.txt')).toBeNull();
    expect(input).toHaveValue('draft'); expect(input).toHaveFocus();
});

test('a clicked reference and focused file can be deleted, and arrows traverse resources', () => {
    render(<Composer />);
    fireEvent.click(screen.getByRole('button', { name: '/word', exact: true }));
    fireEvent.keyDown(document.activeElement!, { key: 'Delete' });
    expect(screen.queryByRole('button', { name: '/word', exact: true })).toBeNull();
    expect(screen.getByRole('button', { name: '/excel', exact: true })).toHaveFocus();
    fireEvent.keyDown(document.activeElement!, { key: 'ArrowLeft' });
    expect(document.activeElement).toHaveTextContent('notes.txt');
    fireEvent.keyDown(document.activeElement!, { key: 'Delete' });
    expect(screen.queryByText('notes.txt')).toBeNull();
    fireEvent.keyDown(document.activeElement!, { key: 'ArrowRight' });
    expect(screen.getByRole('textbox')).toHaveFocus();
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'ArrowLeft' });
    expect(screen.getByRole('button', { name: '/excel', exact: true })).toHaveFocus();
});

test.each([
    { start: 1, end: 1 }, { start: 0, end: 3 }, { start: 0, end: 0, isComposing: true },
    { start: 0, end: 0, keyCode: 229 }, { start: 0, end: 0, metaKey: true },
    { start: 0, end: 0, key: 'Delete' },
])('native text editing is preserved for %j', ({ start, end, ...keys }) => {
    render(<Composer />);
    const input = screen.getByRole('textbox') as HTMLTextAreaElement;
    input.setSelectionRange(start, end);
    fireEvent.keyDown(input, { key: 'Backspace', ...keys });
    expect(screen.getByRole('button', { name: '/excel', exact: true })).toBeInTheDocument();
});

test.each([{ disabled: true }, { composing: true }])('resource deletion respects %j', (props) => {
    render(<Composer {...props} />);
    const input = screen.getByRole('textbox') as HTMLTextAreaElement;
    input.setSelectionRange(0, 0); fireEvent.keyDown(input, { key: 'Backspace' });
    expect(screen.getByRole('button', { name: '/excel', exact: true })).toBeInTheDocument();
});
