import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
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
        {skills.map((skill) => <ContextResourceCard key={skill.name} label={`/${skill.name}`} icon={null}
            onRemove={disabled ? undefined : () => setSkills(skills.filter((item) => item.name !== skill.name))} />)}
        <textarea defaultValue="draft" />
    </div>;
}

test('backspace at the start removes references then files in visual order and preserves text', () => {
    render(<Composer />);
    const input = screen.getByRole('textbox') as HTMLTextAreaElement;
    input.focus(); input.setSelectionRange(0, 0);
    fireEvent.keyDown(input, { key: 'Backspace' });
    expect(screen.queryByText('/excel')).toBeNull();
    expect(screen.getByText('/word')).toBeInTheDocument();
    fireEvent.keyDown(input, { key: 'Backspace' });
    expect(screen.queryByText('/word')).toBeNull();
    fireEvent.keyDown(input, { key: 'Backspace' });
    expect(screen.queryByText('notes.txt')).toBeNull();
    expect(input).toHaveValue('draft'); expect(input).toHaveFocus();
});

test('a clicked reference and focused file can be deleted, and arrows traverse resources', () => {
    render(<Composer />);
    fireEvent.click(screen.getByText('/word'));
    fireEvent.keyDown(document.activeElement!, { key: 'Delete' });
    expect(screen.queryByText('/word')).toBeNull();
    expect(screen.getByText('/excel').closest('[data-composer-resource]')).toHaveFocus();
    fireEvent.keyDown(document.activeElement!, { key: 'ArrowLeft' });
    expect(document.activeElement).toHaveTextContent('notes.txt');
    fireEvent.keyDown(document.activeElement!, { key: 'Delete' });
    expect(screen.queryByText('notes.txt')).toBeNull();
    fireEvent.keyDown(document.activeElement!, { key: 'ArrowRight' });
    expect(screen.getByRole('textbox')).toHaveFocus();
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'ArrowLeft' });
    expect(screen.getByText('/excel').closest('[data-composer-resource]')).toHaveFocus();
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
    expect(screen.getByText('/excel')).toBeInTheDocument();
});

test.each([{ disabled: true }, { composing: true }])('resource deletion respects %j', (props) => {
    render(<Composer {...props} />);
    const input = screen.getByRole('textbox') as HTMLTextAreaElement;
    input.setSelectionRange(0, 0); fireEvent.keyDown(input, { key: 'Backspace' });
    expect(screen.getByText('/excel')).toBeInTheDocument();
});
