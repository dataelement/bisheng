/**
 * KnowledgeAiInput — chat input for knowledge AI assistant.
 *
 * Features:
 * - Standard <textarea> for text input
 * - Single tag badge (top-left, absolutely positioned)
 * - First line uses text-indent to avoid overlap with the badge
 * - '#' key opens TagPicker; selecting a tag sets the badge (max 1)
 * - Badge dismissible with × button
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { SendIcon } from "~/components/svg";
import { TagPicker } from "./TagPicker";
import type { FolderChatTag } from "~/hooks/useFolderChat";
import { useLocalize } from "~/hooks";
import SpeechToTextComponent from "~/components/Voice/SpeechToText";
import { useGetWorkbenchModelsQuery } from "~/hooks/queries/data-provider";

interface KnowledgeAiInputProps {
    availableTags: { id: number; name: string }[];
    isStreaming: boolean;
    disabled?: boolean;
    onSend: (text: string, files?: any[] | null, tag?: FolderChatTag) => void;
    onStop: () => void;
}

const TAG_TEXT_GAP_PX = 4;

export function KnowledgeAiInput({
    availableTags,
    isStreaming,
    disabled,
    onSend,
    onStop,
}: KnowledgeAiInputProps) {
    const localize = useLocalize();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
    const badgeRef = useRef<HTMLSpanElement>(null);
    const [inputText, setInputText] = useState("");
    const [selectedTag, setSelectedTag] = useState<FolderChatTag | null>(null);
    const [showPicker, setShowPicker] = useState(false);
    const [pickerSearch, setPickerSearch] = useState("");
    const isComposingRef = useRef(false);
    const [badgeIndentPx, setBadgeIndentPx] = useState<number | undefined>(undefined);
    const [textScrollTop, setTextScrollTop] = useState(0);
    const scrollRafRef = useRef<number | null>(null);

    // Voice input: check if ASR model is available
    const { data: modelData } = useGetWorkbenchModelsQuery();
    const showVoice = !!modelData?.asr_model?.id;

    // Auto-resize textarea
    const autoResize = useCallback(() => {
        const el = textareaRef.current;
        if (!el) return;
        el.style.height = "auto";
        el.style.height = `${Math.min(el.scrollHeight, 192)}px`; // max-h-48 = 192px
    }, []);

    useEffect(() => {
        autoResize();
    }, [inputText, autoResize]);

    // Keep exactly 4px gap between the tag badge and the first-line text.
    useEffect(() => {
        const el = badgeRef.current;
        if (!selectedTag || !el) {
            setBadgeIndentPx(undefined);
            return;
        }

        const apply = () => setBadgeIndentPx(el.clientWidth + TAG_TEXT_GAP_PX);
        apply();

        const ro = new ResizeObserver(() => apply());
        ro.observe(el);
        return () => ro.disconnect();
    }, [selectedTag?.id, selectedTag?.name]);

    // Detect '#' trigger for tag picker
    const handleInput = useCallback(
        (e: React.ChangeEvent<HTMLTextAreaElement>) => {
            const val = e.target.value;
            setInputText(val);

            if (isComposingRef.current) return;

            // Check if last character typed is '#' or is part of a '#xxx' pattern
            const cursorPos = e.target.selectionStart ?? val.length;
            const textBefore = val.substring(0, cursorPos);
            const hashIdx = textBefore.lastIndexOf("#");

            if (hashIdx >= 0 && !selectedTag) {
                const afterHash = textBefore.substring(hashIdx + 1);
                if (!afterHash.includes(" ") && !afterHash.includes("\n")) {
                    setShowPicker(true);
                    setPickerSearch(afterHash);
                    return;
                }
            }
            setShowPicker(false);
        },
        [selectedTag]
    );

    // Select a tag from the picker
    const handleTagSelect = useCallback(
        (tagName: string) => {
            const tagObj = availableTags.find((t) => t.name === tagName);
            if (tagObj) {
                setSelectedTag(tagObj);
            }
            setShowPicker(false);

            // Remove the '#...' text from input
            if (textareaRef.current) {
                const cursorPos =
                    textareaRef.current.selectionStart ?? inputText.length;
                const textBefore = inputText.substring(0, cursorPos);
                const hashIdx = textBefore.lastIndexOf("#");
                if (hashIdx >= 0) {
                    const newText =
                        inputText.substring(0, hashIdx) +
                        inputText.substring(cursorPos);
                    setInputText(newText);
                }
            }

            textareaRef.current?.focus();
        },
        [availableTags, inputText]
    );

    // Remove tag badge
    const handleRemoveTag = useCallback(() => {
        setSelectedTag(null);
        textareaRef.current?.focus();
    }, []);

    // Handle send
    const handleSend = useCallback(() => {
        if (isStreaming || disabled || !inputText.trim()) return;
        onSend(inputText.trim(), null, selectedTag ?? undefined);
        setInputText("");
        setSelectedTag(null);
    }, [isStreaming, disabled, inputText, selectedTag, onSend]);

    // Handle keydown
    const handleKeyDown = useCallback(
        (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
            if (isComposingRef.current) return;

            // If a tag is selected and input is empty, allow Delete/Backspace to remove the tag.
            if (selectedTag && !inputText.trim() && (e.key === "Backspace" || e.key === "Delete")) {
                e.preventDefault();
                handleRemoveTag();
                return;
            }

            // Enter to send (no Shift)
            if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                if (showPicker) return; // Let TagPicker handle
                handleSend();
            }

            // Escape closes picker
            if (e.key === "Escape" && showPicker) {
                setShowPicker(false);
            }
        },
        [showPicker, handleSend, selectedTag, inputText, handleRemoveTag]
    );

    const handleTextScroll = useCallback(() => {
        const el = textareaRef.current;
        if (!el) return;
        if (scrollRafRef.current) window.cancelAnimationFrame(scrollRafRef.current);
        scrollRafRef.current = window.requestAnimationFrame(() => {
            setTextScrollTop(el.scrollTop || 0);
        });
    }, []);

    useEffect(() => {
        return () => {
            if (scrollRafRef.current) window.cancelAnimationFrame(scrollRafRef.current);
        };
    }, []);

    return (
        <div className="px-4 pb-4 shrink-0">
            <div className="relative pb-3 flex w-full flex-col bg-surface-tertiary rounded-xl">
                {/* Tag picker popup */}
                {showPicker && (
                    <div className="px-3">
                        <TagPicker
                            tags={availableTags
                                .filter((t) => !selectedTag || t.id !== selectedTag.id)
                                .map((t) => t.name)}
                            searchText={pickerSearch}
                            onSelect={handleTagSelect}
                            onClose={() => setShowPicker(false)}
                        />
                    </div>
                )}

                {/* Textarea with tag badge */}
                <div className="relative p-3 pb-0 overflow-hidden">
                    {/* Tag badge — positioned top-left */}
                    {selectedTag && (
                        <span
                            ref={badgeRef}
                            className="absolute top-3 left-3 z-10 inline-flex items-center gap-1 px-2 py-0.5 bg-[rgba(51,92,255,0.35)] text-[#335CFF] text-xs rounded-[6px] border border-transparent select-none"
                            style={{
                                transform: `translateY(${-textScrollTop}px)`,
                            }}
                        >
                            <span className="truncate">#{selectedTag.name}</span>
                        </span>
                    )}

                    <textarea
                        ref={textareaRef}
                        value={inputText}
                        onChange={handleInput}
                        onKeyDown={handleKeyDown}
                        onCompositionStart={() => {
                            isComposingRef.current = true;
                        }}
                        onCompositionEnd={() => {
                            isComposingRef.current = false;
                        }}
                        onScroll={handleTextScroll}
                        disabled={disabled}
                        placeholder={localize("com_knowledge.ai_input_placeholder")}
                        rows={1}
                        className="w-full bg-transparent text-sm outline-none resize-none max-h-48 overflow-y-auto pr-6"
                        style={{
                            textIndent: selectedTag ? `${badgeIndentPx ?? 0}px` : undefined,
                        }}
                        data-testid="knowledge-ai-input"
                    />
                </div>

                {/* Toolbar row */}
                <div className="relative h-8">
                    {/* Send / Stop / Voice buttons */}
                    <div className="absolute bottom-0 right-3 flex gap-2 items-center">
                        {/* Voice input (Speech to Text) */}
                        {showVoice && (
                            <SpeechToTextComponent
                                disabled={disabled}
                                onChange={(e) => {
                                    const newText = (inputText || "") + e;
                                    setInputText(newText);
                                }}
                            />
                        )}

                        {isStreaming ? (
                            <button
                                type="button"
                                className="rounded-full bg-primary p-1 text-text-primary outline-offset-4 transition-all duration-200"
                                onClick={onStop}
                                aria-label="Stop generating"
                            >
                                <svg
                                    width="24"
                                    height="24"
                                    viewBox="0 0 24 24"
                                    fill="none"
                                    xmlns="http://www.w3.org/2000/svg"
                                    className="icon-lg text-surface-primary"
                                >
                                    <rect
                                        x="7"
                                        y="7"
                                        width="10"
                                        height="10"
                                        rx="1.25"
                                        fill="currentColor"
                                    />
                                </svg>
                            </button>
                        ) : (
                            <button
                                type="button"
                                onClick={handleSend}
                                disabled={disabled || !inputText.trim()}
                                className="rounded-full bg-primary p-1 text-text-primary outline-offset-4 transition-all duration-200 disabled:cursor-not-allowed disabled:text-text-secondary disabled:opacity-10"
                                aria-label="Send message"
                                data-testid="send-button"
                            >
                                <SendIcon size={24} />
                            </button>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
}
