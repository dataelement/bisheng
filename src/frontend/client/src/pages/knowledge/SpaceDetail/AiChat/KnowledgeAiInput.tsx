/**
 * KnowledgeAiInput — chat input for knowledge AI assistant.
 *
 * Features:
 * - Standard <textarea> for text input
 * - Tag badge overlays top-left of first line; text-indent clears the badge; outer wrapper scrolls so badge moves with text
 * - '#' key opens TagPicker; selecting a tag sets the badge (max 1)
 * - With tag selected and empty input: first Backspace/Delete highlights tag; second removes it (no extra chrome)
 */
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useRecoilState } from "recoil";
import { SendIcon } from "~/components/svg";
import AiModelSelect from "~/components/Chat/AiModelSelect";
import type { BsConfig } from "~/api/chatApi";
import { TagPicker } from "./TagPicker";
import type { FolderChatTag } from "~/hooks/useFolderChat";
import { useLocalize } from "~/hooks";
import SpeechToTextComponent from "~/components/Voice/SpeechToText";
import { useGetWorkbenchModelsQuery } from "~/hooks/queries/data-provider";
import store from "~/store";

interface KnowledgeAiInputProps {
    availableTags: { id: number; name: string }[];
    modelOptions?: BsConfig["models"];
    modelValue?: number;
    isStreaming: boolean;
    disabled?: boolean;
    onSend: (text: string, files?: any[] | null, tag?: FolderChatTag) => void;
    onStop: () => void;
}

const TAG_TEXT_GAP_PX = 4;

/** Tag chip: background #335CFF @ ~35% alpha; label text #212121 */
const TAG_BG = "#335CFF59";
const TAG_TEXT_CLASS = "text-[#212121]";

export function KnowledgeAiInput({
    availableTags,
    modelOptions,
    modelValue = 0,
    isStreaming,
    disabled,
    onSend,
    onStop,
}: KnowledgeAiInputProps) {
    const localize = useLocalize();
    const [, setChatModel] = useRecoilState(store.chatModel);
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const badgeRef = useRef<HTMLSpanElement>(null);
    const [badgeIndentPx, setBadgeIndentPx] = useState<number | undefined>(undefined);
    const [inputText, setInputText] = useState("");
    const [selectedTag, setSelectedTag] = useState<FolderChatTag | null>(null);
    const [showPicker, setShowPicker] = useState(false);
    const [pickerSearch, setPickerSearch] = useState("");
    const [tagDeleteHighlight, setTagDeleteHighlight] = useState(false);
    const isComposingRef = useRef(false);

    // Voice input: check if ASR model is available
    const { data: modelData } = useGetWorkbenchModelsQuery();
    const showVoice = !!modelData?.asr_model?.id;

    // Grow textarea with content; outer wrapper applies max-h-48 + scroll so tag and text scroll together.
    const autoResize = useCallback(() => {
        const el = textareaRef.current;
        if (!el) return;
        el.style.height = "auto";
        el.style.height = `${el.scrollHeight}px`;
    }, []);

    useEffect(() => {
        autoResize();
    }, [inputText, autoResize]);

    // First-line indent = badge width + gap so wrapped lines use full width under the badge.
    useEffect(() => {
        const el = badgeRef.current;
        if (!selectedTag || !el) {
            setBadgeIndentPx(undefined);
            return;
        }
        const apply = () => setBadgeIndentPx(el.offsetWidth + TAG_TEXT_GAP_PX);
        apply();
        const ro = new ResizeObserver(() => apply());
        ro.observe(el);
        return () => ro.disconnect();
    }, [selectedTag?.id, selectedTag?.name]);

    useEffect(() => {
        setTagDeleteHighlight(false);
    }, [selectedTag?.id]);

    useEffect(() => {
        if (inputText.trim()) setTagDeleteHighlight(false);
    }, [inputText]);

    // 已选 tag 时仅用短文案；部分浏览器不会随 React placeholder 属性刷新，需同步到 DOM
    const resolvedPlaceholder = selectedTag
        ? localize("com_knowledge.ai_input_placeholder_short")
        : localize("com_knowledge.ai_input_placeholder");
    useLayoutEffect(() => {
        const el = textareaRef.current;
        if (el) {
            el.placeholder = resolvedPlaceholder;
        }
    }, [resolvedPlaceholder]);

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
        setTagDeleteHighlight(false);
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

            const raw = e.currentTarget.value;

            // Empty input + tag: 1st Backspace/Delete highlights tag, 2nd removes it
            if (
                selectedTag &&
                !raw.trim() &&
                (e.key === "Backspace" || e.key === "Delete")
            ) {
                e.preventDefault();
                if (tagDeleteHighlight) {
                    handleRemoveTag();
                } else {
                    setTagDeleteHighlight(true);
                }
                return;
            }

            // Enter to send (no Shift)
            if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                if (showPicker) return; // Let TagPicker handle
                handleSend();
            }

            if (e.key === "Escape") {
                if (showPicker) {
                    setShowPicker(false);
                    return;
                }
                if (tagDeleteHighlight) {
                    e.preventDefault();
                    setTagDeleteHighlight(false);
                }
            }
        },
        [showPicker, handleSend, selectedTag, tagDeleteHighlight, handleRemoveTag]
    );

    return (
        <div className="px-4 pb-4 shrink-0">
            <div className="relative flex w-full flex-col rounded-xl bg-surface-tertiary pb-3">
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

                {/* Outer scroll: badge + textarea are one block so they scroll together; badge overlays first line only */}
                <div className="p-3 pb-10">
                    <div className="max-h-48 overflow-y-auto overflow-x-hidden scrollbar-on-hover pr-6">
                        <div className="relative">
                            {selectedTag && (
                                <span
                                    ref={badgeRef}
                                    className={`absolute left-0 top-0 z-10 box-border inline-flex h-5 max-h-5 min-h-5 max-w-[min(240px,90%)] shrink-0 items-center rounded-[2px] px-0 text-xs font-medium leading-none ${TAG_TEXT_CLASS} select-none transition-[background-color,box-shadow] duration-150 ease-out`}
                                    style={{
                                        boxSizing: "border-box",
                                        backgroundColor: tagDeleteHighlight
                                            ? "rgba(51, 92, 255, 0.28)"
                                            : TAG_BG,
                                        boxShadow: tagDeleteHighlight
                                            ? "inset 0 0 0 1.5px #335CFF"
                                            : "inset 0 0 0 1.5px rgba(51, 92, 255, 0)",
                                    }}
                                    aria-selected={tagDeleteHighlight}
                                >
                                    <span
                                        className={`min-w-0 max-w-full overflow-hidden text-ellipsis whitespace-nowrap ${TAG_TEXT_CLASS}`}
                                    >
                                        #{selectedTag.name}
                                    </span>
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
                                disabled={disabled || isStreaming}
                                placeholder={resolvedPlaceholder}
                                rows={1}
                                className="w-full min-h-5 bg-transparent text-sm leading-5 text-text-primary outline-none resize-none overflow-hidden"
                                style={{
                                    textIndent: selectedTag ? `${badgeIndentPx ?? 0}px` : undefined,
                                }}
                                data-testid="knowledge-ai-input"
                            />
                        </div>
                    </div>
                </div>

                <div className="absolute bottom-3 left-3 flex items-center">
                    <AiModelSelect
                        options={modelOptions}
                        value={modelValue}
                        disabled={disabled || isStreaming || !modelOptions?.length}
                        onChange={(val) => {
                            const model = modelOptions?.find((item) => String(item.id) === String(val));
                            setChatModel({
                                id: Number(val),
                                name: model?.displayName || "",
                            });
                        }}
                    />
                </div>

                {/* Send / Stop / Voice buttons */}
                <div className="absolute bottom-3 right-3 flex items-center gap-2">
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
    );
}
