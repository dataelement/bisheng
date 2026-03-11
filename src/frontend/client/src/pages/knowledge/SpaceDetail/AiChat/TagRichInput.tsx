/**
 * TagRichInput — contentEditable rich text input with inline tag capsules.
 *
 * Supports:
 * - Normal text input
 * - '#' triggers TagPicker, selected tag inserts as inline capsule
 * - Backspace at capsule boundary deletes entire capsule
 * - Enter to submit, Shift+Enter for newline
 * - IME composition support (compositionstart/end)
 * - Serializes to: text "tag1" more text "tag2" format
 * - Deserializes: "tag" patterns → capsule DOM nodes
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { cn, removeFocusRings } from "~/utils";
import { TagPicker } from "./TagPicker";

interface TagRichInputProps {
    availableTags: string[];
    placeholder?: string;
    disabled?: boolean;
    onSend: (serialized: string, tags: string[]) => void;
    className?: string;
}

// Capsule data attribute
const TAG_ATTR = "data-tag";

/**
 * Create a capsule HTML span for a tag.
 */
function createCapsuleHTML(tag: string): string {
    return `<span contenteditable="false" ${TAG_ATTR}="${tag}" class="tag-capsule">#${tag}</span>`;
}

/**
 * Serialize contentEditable innerHTML → plain string with "tag" markers.
 */
function serializeContent(el: HTMLDivElement): { text: string; tags: string[] } {
    const tags: string[] = [];
    let text = "";

    const walk = (node: Node) => {
        if (node.nodeType === Node.TEXT_NODE) {
            text += node.textContent || "";
        } else if (node.nodeType === Node.ELEMENT_NODE) {
            const element = node as HTMLElement;
            if (element.hasAttribute(TAG_ATTR)) {
                const tag = element.getAttribute(TAG_ATTR)!;
                tags.push(tag);
                text += `"${tag}"`;
            } else if (element.tagName === "BR") {
                text += "\n";
            } else {
                // Recurse into other elements (e.g. divs from Enter key)
                for (const child of Array.from(element.childNodes)) {
                    walk(child);
                }
                // Divs created by contentEditable on Enter add implicit newlines
                if (element.tagName === "DIV" && element !== el) {
                    text += "\n";
                }
            }
        }
    };

    for (const child of Array.from(el.childNodes)) {
        walk(child);
    }

    return { text: text.trim(), tags: [...new Set(tags)] };
}

/**
 * Place cursor after a given node.
 */
function placeCursorAfter(node: Node) {
    const sel = window.getSelection();
    if (!sel) return;
    const range = document.createRange();
    range.setStartAfter(node);
    range.collapse(true);
    sel.removeAllRanges();
    sel.addRange(range);
}

export function TagRichInput({
    availableTags,
    placeholder = "请输入你的问题，输入 # 可指定标签回答...",
    disabled = false,
    onSend,
    className,
}: TagRichInputProps) {
    const editorRef = useRef<HTMLDivElement>(null);
    const [showPicker, setShowPicker] = useState(false);
    const [pickerSearch, setPickerSearch] = useState("");
    const [isEmpty, setIsEmpty] = useState(true);
    const isComposingRef = useRef(false);

    // Track whether editor is empty (for placeholder)
    const updateEmpty = useCallback(() => {
        if (!editorRef.current) return;
        const text = editorRef.current.textContent || "";
        setIsEmpty(text.trim().length === 0 && editorRef.current.querySelectorAll(`[${TAG_ATTR}]`).length === 0);
    }, []);

    // Detect '#' for tag picker
    const checkHashTrigger = useCallback(() => {
        if (isComposingRef.current) return;
        const sel = window.getSelection();
        if (!sel || !sel.rangeCount) {
            setShowPicker(false);
            return;
        }

        const range = sel.getRangeAt(0);
        const node = range.startContainer;
        if (node.nodeType !== Node.TEXT_NODE) {
            setShowPicker(false);
            return;
        }

        const textBefore = (node.textContent || "").substring(0, range.startOffset);
        const hashIdx = textBefore.lastIndexOf("#");

        if (hashIdx >= 0) {
            const afterHash = textBefore.substring(hashIdx + 1);
            // Only trigger if no space after #
            if (!afterHash.includes(" ") && !afterHash.includes("\n")) {
                setShowPicker(true);
                setPickerSearch(afterHash);
                return;
            }
        }

        setShowPicker(false);
    }, []);

    const handleInput = useCallback(() => {
        updateEmpty();
        checkHashTrigger();
    }, [updateEmpty, checkHashTrigger]);

    // Insert a tag capsule at the current cursor position
    const handleTagSelect = useCallback((tag: string) => {
        if (!editorRef.current) return;

        const sel = window.getSelection();
        if (!sel || !sel.rangeCount) return;

        const range = sel.getRangeAt(0);
        const node = range.startContainer;

        // Remove the '#...' text that triggered the picker
        if (node.nodeType === Node.TEXT_NODE) {
            const text = node.textContent || "";
            const offset = range.startOffset;
            const hashIdx = text.lastIndexOf("#", offset - 1);
            if (hashIdx >= 0) {
                // Split: keep text before '#', remove '#...' up to cursor
                node.textContent = text.substring(0, hashIdx) + text.substring(offset);
                // Set cursor to where '#' was
                range.setStart(node, hashIdx);
                range.collapse(true);
            }
        }

        // Insert capsule
        const capsule = document.createElement("span");
        capsule.contentEditable = "false";
        capsule.setAttribute(TAG_ATTR, tag);
        capsule.className = "tag-capsule";
        capsule.textContent = `#${tag}`;

        range.insertNode(capsule);

        // Add a space after the capsule for continued typing
        const space = document.createTextNode("\u00A0");
        capsule.after(space);
        placeCursorAfter(space);

        setShowPicker(false);
        updateEmpty();
        editorRef.current.focus();
    }, [updateEmpty]);

    // Handle keydown
    const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLDivElement>) => {
        if (isComposingRef.current) return;

        // Enter to send (no shift)
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            if (showPicker) return; // Let TagPicker handle Enter
            if (!editorRef.current || disabled) return;

            const { text, tags } = serializeContent(editorRef.current);
            if (!text.trim()) return;

            onSend(text, tags);
            // Clear editor
            editorRef.current.innerHTML = "";
            updateEmpty();
            return;
        }

        // Backspace: check if previous sibling is a capsule
        if (e.key === "Backspace") {
            const sel = window.getSelection();
            if (!sel || !sel.rangeCount) return;
            const range = sel.getRangeAt(0);

            if (range.collapsed && range.startOffset === 0 && range.startContainer.nodeType === Node.TEXT_NODE) {
                const prev = range.startContainer.previousSibling;
                if (prev && prev.nodeType === Node.ELEMENT_NODE && (prev as HTMLElement).hasAttribute(TAG_ATTR)) {
                    e.preventDefault();
                    prev.parentNode?.removeChild(prev);
                    updateEmpty();
                    return;
                }
            }

            // Also check when cursor is at start of editor or at element level
            if (range.collapsed && range.startContainer === editorRef.current && range.startOffset > 0) {
                const prevChild = editorRef.current.childNodes[range.startOffset - 1];
                if (prevChild && prevChild.nodeType === Node.ELEMENT_NODE && (prevChild as HTMLElement).hasAttribute(TAG_ATTR)) {
                    e.preventDefault();
                    prevChild.parentNode?.removeChild(prevChild);
                    updateEmpty();
                    return;
                }
            }
        }
    }, [showPicker, disabled, onSend, updateEmpty]);

    // IME support
    const handleCompositionStart = useCallback(() => {
        isComposingRef.current = true;
    }, []);

    const handleCompositionEnd = useCallback(() => {
        isComposingRef.current = false;
        handleInput();
    }, [handleInput]);

    // Collect currently used tags (for filtering picker)
    const getUsedTags = useCallback((): string[] => {
        if (!editorRef.current) return [];
        const capsules = editorRef.current.querySelectorAll(`[${TAG_ATTR}]`);
        return Array.from(capsules).map(el => el.getAttribute(TAG_ATTR)!);
    }, []);

    // Focus editor on mount
    useEffect(() => {
        editorRef.current?.focus();
    }, []);

    return (
        <div className="relative">
            {/* Tag picker popup */}
            {showPicker && (
                <div className="px-3">
                    <TagPicker
                        tags={availableTags.filter(t => !getUsedTags().includes(t))}
                        searchText={pickerSearch}
                        onSelect={handleTagSelect}
                        onClose={() => setShowPicker(false)}
                    />
                </div>
            )}

            {/* ContentEditable editor */}
            <div className="relative">
                <div
                    ref={editorRef}
                    contentEditable={!disabled}
                    suppressContentEditableWarning
                    onInput={handleInput}
                    onKeyDown={handleKeyDown}
                    onCompositionStart={handleCompositionStart}
                    onCompositionEnd={handleCompositionEnd}
                    data-testid="tag-rich-input"
                    className={cn(
                        "p-3 pb-0 m-0 w-full bg-transparent text-sm",
                        "max-h-48 overflow-y-auto pl-4 pr-6 outline-none",
                        "min-h-[56px]",
                        removeFocusRings,
                        className
                    )}
                    style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}
                />
                {/* Placeholder */}
                {isEmpty && (
                    <div className="absolute top-3 left-4 text-sm text-black/50 pointer-events-none select-none">
                        {placeholder}
                    </div>
                )}
            </div>

            {/* Capsule styles */}
            <style>{`
                .tag-capsule {
                    display: inline-flex;
                    align-items: center;
                    padding: 1px 8px;
                    margin: 0 2px;
                    background: #e8f3ff;
                    color: #165dff;
                    font-size: 12px;
                    border-radius: 99px;
                    border: 1px solid #bedaff;
                    user-select: none;
                    vertical-align: baseline;
                    line-height: 20px;
                    cursor: default;
                }
                .tag-capsule:hover {
                    background: #d6e8ff;
                }
            `}</style>
        </div>
    );
}
