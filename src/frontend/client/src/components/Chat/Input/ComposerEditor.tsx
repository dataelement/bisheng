import { forwardRef, useImperativeHandle, useLayoutEffect, useRef } from 'react';
import type { ClipboardEvent, CompositionEvent, KeyboardEvent, UIEvent } from 'react';

export interface ComposerReference {
    key: string;
    label: string;
}

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

/** Read the editable document while keeping reference identity separate from prompt text. */
export function readComposerDocument(root: HTMLElement) {
    const keys: string[] = [];
    const visit = (node: Node): string => {
        if (node.nodeType === Node.TEXT_NODE) return node.textContent || '';
        if (!(node instanceof HTMLElement)) return '';
        const key = node.dataset.composerReference;
        if (key) { keys.push(key); return ''; }
        if (node.tagName === 'BR') return node.nextSibling ? '\n' : '';
        const content = Array.from(node.childNodes).map(visit).join('');
        return /^(DIV|P)$/.test(node.tagName) && node !== root && node.previousSibling
            ? `\n${content}` : content;
    };
    return { text: visit(root), keys };
}

function createReference(reference: ComposerReference) {
    const token = document.createElement('span');
    token.dataset.composerReference = reference.key;
    token.contentEditable = 'false';
    token.className = 'dsh-inline-reference';
    token.textContent = reference.label;
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
            bookmark.current = selection.getRangeAt(0).cloneRange();
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
        for (const token of root.querySelectorAll<HTMLElement>(tokenSelector)) {
            if (!wanted.has(token.dataset.composerReference!)) token.remove();
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
