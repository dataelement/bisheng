import type { KeyboardEvent } from 'react';

/** Connect the native textarea caret to the ordered context resources before it. */
export function handleComposerResourceKeyDown(
    event: KeyboardEvent<HTMLDivElement>, disabled: boolean, composing: boolean,
) {
    if (disabled || composing || event.nativeEvent.isComposing || event.keyCode === 229
        || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const root = event.currentTarget;
    const input = root.querySelector<HTMLElement>('textarea, [role="textbox"][contenteditable]');
    const resources = Array.from(root.querySelectorAll<HTMLElement>('[data-composer-resource]'))
        .filter((item) => item.querySelector<HTMLButtonElement>('[data-composer-remove]:enabled'));
    const focusInput = () => {
        input?.focus();
        if (input instanceof HTMLTextAreaElement) input.setSelectionRange(0, 0);
        else if (input) {
            const range = document.createRange();
            range.selectNodeContents(input); range.collapse(true);
            window.getSelection()?.removeAllRanges();
            window.getSelection()?.addRange(range);
        }
    };
    const focusResource = (item: HTMLElement) =>
        (item.querySelector<HTMLElement>('[data-composer-focus]') || item).focus();
    const remove = (item: HTMLElement) => item.querySelector<HTMLButtonElement>('[data-composer-remove]')?.click();
    const consume = () => { event.preventDefault(); event.stopPropagation(); };
    if (target === input || input?.contains(target)) {
        // Native text selections, IME edits and all other caret positions stay native.
        if (!resources.length || !input) return;
        if (input instanceof HTMLTextAreaElement) {
            if (input.selectionStart !== 0 || input.selectionEnd !== 0) return;
        } else {
            const selection = window.getSelection();
            if (!selection?.isCollapsed || !selection.rangeCount || !input.contains(selection.anchorNode)) return;
            const before = selection.getRangeAt(0).cloneRange();
            before.selectNodeContents(input);
            before.setEnd(selection.anchorNode!, selection.anchorOffset);
            const contents = before.cloneContents();
            if (contents.textContent || contents.querySelector('[data-composer-reference],br')) return;
        }
        const last = resources[resources.length - 1];
        if (event.key === 'Backspace') { consume(); remove(last); focusInput(); }
        if (event.key === 'ArrowLeft') { consume(); focusResource(last); }
        return;
    }
    const current = target.closest<HTMLElement>('[data-composer-resource]');
    const index = current ? resources.indexOf(current) : -1;
    if (!current || index < 0) return;
    if (event.key === 'Backspace' || event.key === 'Delete') {
        consume();
        const neighbor = resources[event.key === 'Backspace' ? index - 1 : index + 1];
        remove(current);
        if (neighbor) focusResource(neighbor); else focusInput();
    } else if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
        consume();
        const neighbor = resources[event.key === 'ArrowLeft' ? index - 1 : index + 1];
        if (neighbor) focusResource(neighbor);
        else if (event.key === 'ArrowRight') focusInput();
    }
}
