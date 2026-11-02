import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { ComposerEditor, readComposerDocument } from './ComposerEditor';
import { useComposerReferences } from './useComposerReferences';

function Harness({ disabled = false }) {
    const [text, setText] = useState('before after');
    const [skills, setSkills] = useState([{ name: 'ppt', display_name: 'PPT' }]);
    const { references, onReferencesChange } = useComposerReferences(skills, [], setSkills);
    return <>
        <ComposerEditor value={text} onChange={setText} references={references}
            onReferencesChange={onReferencesChange} onKeyDown={() => {}}
            placeholder="Write" disabled={disabled} />
        <output data-testid="text">{text}</output>
        <output data-testid="skills">{skills.map((item) => item.name).join(',')}</output>
        <button onClick={() => setSkills([...skills, { name: 'word', display_name: 'Word' }])}>add</button>
    </>;
}

function select(node: Node, start: number, end = start) {
    const range = document.createRange();
    range.setStart(node, start); range.setEnd(node, end);
    window.getSelection()?.removeAllRanges(); window.getSelection()?.addRange(range);
}

test('references and editable text share the same DOM and line flow', () => {
    render(<Harness />);
    const editor = screen.getByRole('textbox');
    expect(editor).toContainElement(screen.getByText('/PPT'));
    expect(editor.textContent).toBe('/PPTbefore after');
    expect(editor.querySelector('textarea')).toBeNull();
    expect(screen.getByTestId('text')).toHaveTextContent('before after');
});

test('a reference removed in the native document updates IDs, and undo restores its metadata', () => {
    render(<Harness />);
    const editor = screen.getByRole('textbox');
    const token = screen.getByText('/PPT');
    token.remove(); fireEvent.input(editor);
    expect(screen.getByTestId('skills')).toBeEmptyDOMElement();
    editor.prepend(token); fireEvent.input(editor);
    expect(screen.getByTestId('skills')).toHaveTextContent('ppt');
    expect(screen.getByTestId('text')).toHaveTextContent('before after');
});

test('select-all deletion clears both prompt and selected skills', () => {
    render(<Harness />);
    const editor = screen.getByRole('textbox');
    editor.replaceChildren(); fireEvent.input(editor);
    expect(screen.getByTestId('text')).toBeEmptyDOMElement();
    expect(screen.getByTestId('skills')).toBeEmptyDOMElement();
    expect(editor).toHaveAttribute('data-empty', 'true');
});

test('menu insertion restores the caret in the middle of the sentence', () => {
    render(<Harness />);
    const editor = screen.getByRole('textbox');
    select(editor.lastChild!, 7);
    fireEvent.blur(editor);
    const insert = jest.fn((_command, _show, markup) => {
        const range = window.getSelection()!.getRangeAt(0);
        range.insertNode(range.createContextualFragment(markup));
        return true;
    });
    document.execCommand = insert;
    fireEvent.click(screen.getByText('add'));
    expect(insert).toHaveBeenCalledWith('insertHTML', false, expect.stringContaining('skill:word'));
    expect(editor.textContent).toBe('/PPTbefore /Wordafter');
});

test('IME publishes only the committed text and keeps the active document intact', () => {
    render(<Harness />);
    const editor = screen.getByRole('textbox');
    fireEvent.compositionStart(editor);
    editor.lastChild!.textContent = '中文';
    fireEvent.input(editor);
    expect(screen.getByTestId('text')).toHaveTextContent('before after');
    fireEvent.compositionEnd(editor);
    expect(screen.getByTestId('text')).toHaveTextContent('中文');
    expect(screen.getByTestId('skills')).toHaveTextContent('ppt');
});

test('paste inserts plain text instead of trusting pasted markup or reference IDs', () => {
    render(<Harness />);
    document.execCommand = jest.fn();
    fireEvent.paste(screen.getByRole('textbox'), {
        clipboardData: { getData: (type: string) => type === 'text/plain' ? '<hello>' : '<img onerror=alert(1)>' },
    });
    expect(document.execCommand).toHaveBeenCalledWith('insertText', false, '<hello>');
});

test('disabled editor exposes its read-only state', () => {
    render(<Harness disabled />);
    expect(screen.getByRole('textbox')).toHaveAttribute('contenteditable', 'false');
    expect(screen.getByRole('textbox')).toHaveAttribute('aria-disabled', 'true');
});

test('browser paragraph and trailing caret markers serialize to prompt newlines', () => {
    const editor = document.createElement('div');
    editor.innerHTML = 'first<div>second</div><div><br></div>';
    expect(readComposerDocument(editor).text).toBe('first\nsecond\n');
    editor.innerHTML = '<br>';
    expect(readComposerDocument(editor).text).toBe('');
});
