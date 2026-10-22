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

function RepeatedSelectionHarness() {
    const [skills, setSkills] = useState<{ name: string }[]>([]);
    const binding = useComposerReferences(skills, [], setSkills);
    return <>
        <ComposerEditor value="" onChange={() => {}} {...binding} onKeyDown={() => {}} placeholder="Write" />
        <button onClick={() => setSkills(previous => [...previous, { name: `skill-${previous.length}` }])}>select next</button>
    </>;
}

test('consecutive menu insertions continue outside Chromium non-editable token caret positions', () => {
    render(<RepeatedSelectionHarness />);
    const editor = screen.getByRole('textbox');
    document.execCommand = jest.fn((_command, _show, markup = '') => {
        const range = window.getSelection()!.getRangeAt(0);
        const container = range.startContainer;
        const element = container instanceof Element ? container : container.parentElement;
        if (element?.closest('[contenteditable="false"]')) return false;
        const fragment = range.createContextualFragment(markup);
        const token = fragment.lastChild!;
        range.insertNode(fragment);
        // Match Chromium's native caret inside the inserted token's text.
        select(token.firstChild!, token.textContent!.length);
        return true;
    });
    const add = screen.getByRole('button', { name: 'select next' });
    fireEvent.click(add);
    fireEvent.click(add);
    fireEvent.click(add);
    // Undo and pointer restoration can also report a collapsed token caret.
    const lastToken = editor.querySelectorAll('[data-composer-reference]')[2];
    select(lastToken.firstChild!, lastToken.textContent!.length);
    fireEvent.blur(editor);
    fireEvent.click(add);
    expect(readComposerDocument(editor)).toEqual({ text: '', keys: ['skill:skill-0', 'skill:skill-1', 'skill:skill-2', 'skill:skill-3'] });
    expect(window.getSelection()!.anchorNode).toBe(editor);
});

test('IME publishes only the committed text and keeps the active document intact', () => {
    render(<Harness />);
    const editor = screen.getByRole('textbox');
    fireEvent.compositionStart(editor);
    // eslint-disable-next-line no-restricted-syntax -- Chinese text is IME input data, not UI copy.
    const committedText = '中文';
    editor.lastChild!.textContent = committedText;
    fireEvent.input(editor);
    expect(screen.getByTestId('text')).toHaveTextContent('before after');
    fireEvent.compositionEnd(editor);
    expect(screen.getByTestId('text')).toHaveTextContent(committedText);
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


test('empty focused editor keeps its hint until IME draft text arrives and restores it when cleared', () => {
    render(<Harness />);
    const editor = screen.getByRole('textbox');
    editor.replaceChildren();
    fireEvent.input(editor);
    fireEvent.focus(editor);
    expect(editor).toHaveAttribute('data-empty', 'true');

    fireEvent.compositionStart(editor);
    editor.textContent = "ni'hao";
    fireEvent.input(editor);
    expect(editor).toHaveAttribute('data-empty', 'false');
    expect(screen.getByTestId('text')).toBeEmptyDOMElement();

    editor.textContent = '你好';
    fireEvent.compositionEnd(editor);
    expect(screen.getByTestId('text')).toHaveTextContent('你好');
    expect(editor).toHaveAttribute('data-empty', 'false');

    editor.replaceChildren();
    fireEvent.input(editor);
    expect(editor).toHaveAttribute('data-empty', 'true');
    expect(screen.getByTestId('text')).toBeEmptyDOMElement();
});

function ToolHarness() {
    const [text, setText] = useState('Check inventory');
    const [tools, setTools] = useState([
        { id: 12, name: 'Inventory', children: [{ id: 41, tool_key: 'inventory' }] },
        { id: 13, name: 'Time', children: [{ id: 1, tool_key: 'get_current_time' }] },
    ]);
    const binding = useComposerReferences([], [], () => {}, undefined, tools, setTools);
    return <>
        <ComposerEditor value={text} onChange={setText} {...binding} onKeyDown={() => {}} placeholder="Write" />
        <output data-testid="tool-payload">{JSON.stringify(tools)}</output>
        <output data-testid="prompt">{text}</output>
        <button onClick={() => setTools(previous => previous.filter(tool => tool.id !== 12))}>uncheck inventory</button>
    </>;
}

test('inline tools preserve executable children while staying outside prompt text', () => {
    render(<ToolHarness />);
    const editor = screen.getByRole('textbox');
    expect(editor).toContainElement(screen.getByText('/Inventory'));
    expect(readComposerDocument(editor)).toEqual({ text: 'Check inventory', keys: ['tool:12', 'tool:13'] });
    const inventory = screen.getByText('/Inventory');
    inventory.remove(); fireEvent.input(editor);
    expect(JSON.parse(screen.getByTestId('tool-payload').textContent!)).toEqual([
        { id: 13, name: 'Time', children: [{ id: 1, tool_key: 'get_current_time' }] },
    ]);
    editor.prepend(inventory); fireEvent.input(editor);
    expect(JSON.parse(screen.getByTestId('tool-payload').textContent!)[0].children).toEqual([{ id: 41, tool_key: 'inventory' }]);
    expect(screen.getByTestId('prompt')).toHaveTextContent('Check inventory');
});

test('unchecking tools and clearing the document update both reference and selection state', () => {
    render(<ToolHarness />);
    fireEvent.click(screen.getByRole('button', { name: 'uncheck inventory' }));
    expect(screen.queryByText('/Inventory')).toBeNull();
    expect(screen.getByText('/Time')).toBeInTheDocument();
    const editor = screen.getByRole('textbox');
    editor.replaceChildren(); fireEvent.input(editor);
    expect(screen.getByTestId('tool-payload')).toHaveTextContent('[]');
    expect(screen.getByTestId('prompt')).toBeEmptyDOMElement();
});
