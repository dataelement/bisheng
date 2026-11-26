import { forwardRef, useImperativeHandle, useLayoutEffect, useRef } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import type { ClipboardEvent, CompositionEvent, KeyboardEvent, UIEvent } from 'react';
import { InlineChatReference } from '../InlineChatReference';
import type { ComposerReference, SentComposerReference } from './composerReferences';

interface ComposerEditorProps {
    value: string;
    references: ComposerReference[];
    disabled?: boolean;
    placeholder: string;
    className?: string;
    onChange: (value: string) => void;
    onReferencesChange: (keys: string[]) => void;
    onKeyDown: (event: KeyboardEvent<HTMLDivElement>) => void;
    onPaste?: (event: ClipboardEvent<HTMLDivElement>) => void;
    onScroll?: (event: UIEvent<HTMLDivElement>) => void;
    onCompositionStart?: (event: CompositionEvent<HTMLDivElement>) => void;
    onCompositionEnd?: (event: CompositionEvent<HTMLDivElement>) => void;
}

const tokenSelector = '[data-composer-reference]';

function readComposerParts(root: HTMLElement) {
    let text = '';
    const positions: { key: string; offset: number }[] = [];
    const visit = (node: Node): void => {
        if (node.nodeType === Node.TEXT_NODE) {
            text += node.textContent || '';
            return;
        }
        if (!(node instanceof HTMLElement)) return;
        const key = node.dataset.composerReference;
        if (key) {
            positions.push({ key, offset: text.length });
            return;
        }
        if (node.tagName === 'BR') {
            if (node.nextSibling) text += '\n';
            return;
        }
        if (/^(DIV|P)$/.test(node.tagName) && node !== root && node.previousSibling) text += '\n';
        node.childNodes.forEach(visit);
    };
    visit(root);
    return { text, positions };
}

/** Read the editable document while keeping reference identity separate from prompt text. */
export function readComposerDocument(root: HTMLElement) {
    const { text, positions } = readComposerParts(root);
    return { text, keys: positions.map(({ key }) => key) };
}

export function readSentComposerReferences(
    root: HTMLElement,
    references: ComposerReference[],
): SentComposerReference[] {
    if (!references.length) return [];
    const { text, positions } = readComposerParts(root);
    const start = text.length - text.trimStart().length;
    const length = text.trim().length;
    const byKey = new Map(references.map((reference) => [reference.key, reference]));
    return positions.flatMap(({ key, offset }) => {
        const reference = byKey.get(key);
        if (!reference) return [];
        return [{
            kind: reference.kind,
            label: reference.label,
            offset: Math.max(0, Math.min(offset - start, length)),
            ...(reference.is_tag ? { is_tag: reference.is_tag } : {}),
        }];
    });
}

export function insertComposerPrompt(root: HTMLElement, prompt: string): boolean {
    const selection = root.ownerDocument.getSelection();
    if (!selection || typeof root.ownerDocument.execCommand !== 'function') return false;
    const { text, keys } = readComposerDocument(root);
    const hasReferences = keys.length > 0;
    if (!hasReferences && text === prompt) {
        root.focus({ preventScroll: true });
        return true;
    }
    const range = root.ownerDocument.createRange();
    root.focus({ preventScroll: true });
    range.selectNodeContents(root);
    if (hasReferences) range.collapse(false);
    selection.removeAllRanges();
    selection.addRange(range);
    // Use the same native edit transaction as paste so input events and undo still work.
    return root.ownerDocument.execCommand('insertText', false, hasReferences && text ? `\n\n${prompt}` : prompt);
}


function createReference(reference: ComposerReference) {
    const template = document.createElement('template');
    template.innerHTML = renderToStaticMarkup(
        <InlineChatReference kind={reference.is_tag ? 'tag' : reference.kind} label={reference.label} />,
    );
    const token = template.content.firstElementChild as HTMLSpanElement;
    token.dataset.composerReference = reference.key;
    token.setAttribute('contenteditable', 'false');
    return token;
}

/** One native editing surface owns text, references, selection and the undo stack. */
export const ComposerEditor = forwardRef<HTMLDivElement, ComposerEditorProps>(function ComposerEditor({
    value, references, disabled, placeholder, className, onChange, onReferencesChange,
    onKeyDown, onPaste, onScroll, onCompositionStart, onCompositionEnd,
}, forwardedRef) {
    const rootRef = useRef<HTMLDivElement>(null);
    const bookmark = useRef<Range | null>(null);
    const composing = useRef(false);
    const callbacks = useRef({ onChange, onReferencesChange });
    callbacks.current = { onChange, onReferencesChange };
    useImperativeHandle(forwardedRef, () => rootRef.current!, []);

    const saveSelection = () => {
        const selection = window.getSelection();
        if (selection?.rangeCount && rootRef.current?.contains(selection.anchorNode)) {
            const range = selection.getRangeAt(0).cloneRange();
            const container = range.startContainer;
            const element = container instanceof HTMLElement ? container : container.parentElement;
            const token = element?.closest(tokenSelector);
            // Chromium may leave a collapsed caret inside a non-editable token
            // after insertion or undo. Continue at its editable sibling boundary.
            if (range.collapsed && token) {
                range.setStartAfter(token); range.collapse(true);
                selection.removeAllRanges(); selection.addRange(range);
            }
            bookmark.current = range;
        }
    };
    const publish = () => {
        const root = rootRef.current;
        if (!root) return;
        const result = readComposerDocument(root);
        callbacks.current.onChange(result.text);
        callbacks.current.onReferencesChange([...new Set(result.keys)]);
        root.dataset.empty = String(!result.text && !result.keys.length);
        saveSelection();
    };
    const restoreSelection = () => {
        const root = rootRef.current!;
        const saved = bookmark.current;
        const range = saved && root.contains(saved.startContainer) && root.contains(saved.endContainer)
            ? saved : document.createRange();
        if (range !== saved) { range.selectNodeContents(root); range.collapse(false); }
        root.focus();
        const selection = window.getSelection();
        selection?.removeAllRanges();
        selection?.addRange(range);
    };

    useLayoutEffect(() => {
        const root = rootRef.current;
        if (!root || composing.current) return;
        const current = readComposerDocument(root);
        // External prompt replacement (send, preset, voice) is explicit. Normal
        // typing already matches value, so React leaves the live DOM and caret alone.
        if (current.text !== value) {
            const retained = Array.from(root.querySelectorAll<HTMLElement>(tokenSelector));
            root.replaceChildren(...retained, document.createTextNode(value));
            bookmark.current = null;
        }
        const wanted = new Set(references.map((reference) => reference.key));
        const byKey = new Map(references.map((reference) => [reference.key, reference]));
        for (const token of root.querySelectorAll<HTMLElement>(tokenSelector)) {
            if (!wanted.has(token.dataset.composerReference!)) token.remove();
            else {
                const reference = byKey.get(token.dataset.composerReference!)!;
                const label = token.querySelector('.dsh-inline-reference-label');
                if (label && label.textContent !== reference.label) label.textContent = reference.label;
                token.title = reference.label;
            }
        }
        const present = new Set(readComposerDocument(root).keys);
        const added = references.filter((reference) => !present.has(reference.key));
        if (added.length) {
            if (bookmark.current && !disabled) {
                restoreSelection();
                // Native insertion participates in the browser's selection/undo
                // transaction. Markup is constructed from escaped DOM text only.
                document.execCommand('insertHTML', false, added.map((reference) => createReference(reference).outerHTML).join(''));
                saveSelection();
            } else {
                const fragment = document.createDocumentFragment();
                added.forEach((reference) => fragment.append(createReference(reference)));
                const last = fragment.lastChild!;
                root.prepend(fragment);
                const range = document.createRange();
                range.setStartAfter(last); range.collapse(true);
                bookmark.current = range;
            }
        }
        root.dataset.empty = String(!readComposerDocument(root).text && !references.length);
    }, [value, references, disabled]);

    return <div
        ref={rootRef}
        role="textbox"
        aria-multiline="true"
        aria-label={placeholder}
        aria-disabled={disabled}
        data-placeholder={placeholder}
        data-testid="ai-chat-input"
        contentEditable={!disabled}
        suppressContentEditableWarning
        className={`dsh-composer-editor ${className || ''}`}
        onInput={() => {
            if (composing.current) {
                // IME draft text controls placeholder visibility before it is committed.
                const root = rootRef.current;
                if (root) {
                    const draft = readComposerDocument(root);
                    root.dataset.empty = String(!draft.text && !draft.keys.length);
                }
            } else {
                publish();
            }
        }}
        onBlur={saveSelection}
        onKeyUp={saveSelection}
        onMouseUp={saveSelection}
        onClick={(event) => {
            const target = event.target as HTMLElement;
            const token = target.closest(tokenSelector);
            if (disabled || !token) return;
            const range = document.createRange();
            range.selectNode(token);
            const selection = window.getSelection();
            selection?.removeAllRanges();
            selection?.addRange(range);
            saveSelection();
        }}
        onKeyDown={onKeyDown}
        onScroll={onScroll}
        onCompositionStart={(event) => { composing.current = true; onCompositionStart?.(event); }}
        onCompositionEnd={(event) => {
            composing.current = false;
            publish();
            onCompositionEnd?.(event);
        }}
        onPaste={(event) => {
            onPaste?.(event);
            if (event.defaultPrevented || disabled) return;
            event.preventDefault();
            // Pasted HTML never supplies reference IDs or executable markup.
            document.execCommand('insertText', false, event.clipboardData.getData('text/plain'));
        }}
    />;
});
