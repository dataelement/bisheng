/**
 * KnowledgeAiInput — chat input for knowledge AI assistant.
 *
 * Features:
 * - Standard <textarea> for text input
 * - Tag badge overlays top-left of first line; text-indent clears the badge; outer wrapper scrolls so badge moves with text
 * - '#' key opens TagPicker; selecting a tag sets the badge (max 1)
 * - With tag selected and empty input: first Backspace/Delete highlights tag; second removes it (no extra chrome)
 *
 * Variants (frame only — internal layout is identical):
 * - `box`  (default) standalone floating input — rounded-[20px] white card with subtle
 *           border and shadow. Matches the bottom-dock collapsed state.
 * - `line` flush input inside a chat card — no border/shadow/rounded; a thin top divider
 *           visually separates it from the messages above.
 *
 * The component renders no outer padding; the parent owns positioning and spacing.
 */
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useRecoilState } from "recoil";
import { Outlined } from "bisheng-icons";
import { SendIcon } from "~/components/svg";
import { AttachmentChip } from "~/components/Chat/Input/AttachmentBar";
import { KnowledgeChipFileIcon, PagerButton } from "./KnowledgeAttachmentStrip";
import AiModelSelect from "~/components/Chat/AiModelSelect";
import type { BsConfig } from "~/api/chatApi";
import { TagPicker } from "./TagPicker";
import type { FolderChatTag } from "~/hooks/useFolderChat";
import { useLocalize, usePrefersMobileLayout, useScrollRevealRef } from "~/hooks";
import SpeechToTextComponent from "~/components/Voice/SpeechToText";
import { useGetWorkbenchModelsQuery } from "~/hooks/queries/data-provider";
import { cn } from "~/utils";
import store from "~/store";

/** A ticked row shown as a reference chip above the textarea. */
export interface KnowledgeAiReference {
    id: string;
    name: string;
    isFolder: boolean;
}

interface KnowledgeAiInputProps {
    availableTags: { id: number; name: string }[];
    modelOptions?: BsConfig["models"];
    modelValue?: number;
    isStreaming: boolean;
    disabled?: boolean;
    onSend: (text: string, files?: any[] | null, tag?: FolderChatTag) => void;
    onStop: () => void;
    /** Visual frame; see file header. Defaults to "box". */
    variant?: "box" | "line";
    /** Notifies parent when the textarea gains/loses focus — used by the dock to
     *  drive the mobile keyboard-up grey overlay. */
    onFocusChange?: (focused: boolean) => void;
    /** Content ticked in the file list, in tick order. Empty = no reference row at all. */
    selectedContent?: KnowledgeAiReference[];
    /** Removing a chip unticks that row in the file list. */
    onUnselectContent?: (id: string) => void;
    /** The dock renders the ticked content as a grey strip ABOVE this card
     *  (KnowledgeAttachmentStrip, Figma 13022:46625) — suppress the in-card
     *  reference row so the chips don't show twice. `selectedContent` still
     *  drives the placeholder copy. */
    hideReferenceRow?: boolean;
}

const TAG_TEXT_GAP_PX = 4;

/** Tag chip: background #335CFF @ ~35% alpha; label text #212121 */
const TAG_BG = "rgb(var(--brand-500)/0.35)";
const TAG_TEXT_CLASS = "text-[#212121]";

export function KnowledgeAiInput({
    availableTags,
    modelOptions,
    modelValue = 0,
    isStreaming,
    disabled,
    onSend,
    onStop,
    variant = "box",
    onFocusChange,
    selectedContent = [],
    onUnselectContent,
    hideReferenceRow = false,
}: KnowledgeAiInputProps) {
    const outerScrollRevealRef = useScrollRevealRef<HTMLDivElement>();
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
    /** Restacks the input from single-row to two-row when the textarea wraps.
     *  Only escalates (one-way) to avoid oscillation; resets when the input is cleared. */
    const [multiline, setMultiline] = useState(false);
    const isComposingRef = useRef(false);
    const isH5 = usePrefersMobileLayout();

    /** Two-row layout: textarea on top, model + controls below. Single-row otherwise.
     *  Mobile is always two-row (matches the channel article dock) — the extra controls
     *  (tag picker / model / voice) don't fit comfortably on one line on phones. */
    const stacked = variant === "line" || multiline || isH5;

    // Voice input: check if ASR model is available
    const { data: modelData } = useGetWorkbenchModelsQuery();
    const showVoice = !!modelData?.asr_model?.id;

    // Grow textarea with content; outer wrapper applies max-h-48 + scroll so tag and text scroll together.
    // Also escalates the layout to two-row once the text wraps past a single line.
    const autoResize = useCallback(() => {
        const el = textareaRef.current;
        if (!el) return;
        el.style.height = "auto";
        const next = el.scrollHeight;
        el.style.height = `${next}px`;
        // leading-5 = 20px line-height; >30px ≈ second line has wrapped/started.
        if (next > 30) setMultiline(true);
    }, []);

    useEffect(() => {
        autoResize();
    }, [inputText, autoResize]);

    // Reset to single-row when the input is cleared (incl. parent-driven clears on send).
    useEffect(() => {
        if (!inputText) setMultiline(false);
    }, [inputText]);

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

    // Reference-row scroll affordance: white edge fades appear only while content
    // is actually scrolled out of view on that side (mirrors the grey strip).
    const referenceRowRef = useRef<HTMLDivElement>(null);
    const [refCanLeft, setRefCanLeft] = useState(false);
    const [refCanRight, setRefCanRight] = useState(false);
    const updateReferenceEdges = useCallback(() => {
        const el = referenceRowRef.current;
        if (!el) return;
        const maxScroll = el.scrollWidth - el.clientWidth;
        setRefCanLeft(el.scrollLeft > 1);
        setRefCanRight(el.scrollLeft < maxScroll - 1);
    }, []);
    useLayoutEffect(() => {
        updateReferenceEdges();
        const el = referenceRowRef.current;
        if (!el || typeof ResizeObserver === "undefined") return;
        const ro = new ResizeObserver(() => updateReferenceEdges());
        ro.observe(el);
        return () => ro.disconnect();
    }, [updateReferenceEdges, selectedContent.length, hideReferenceRow]);
    const pageReferenceRow = useCallback((dir: "left" | "right") => {
        const el = referenceRowRef.current;
        if (!el) return;
        el.scrollBy({ left: dir === "left" ? -el.clientWidth : el.clientWidth, behavior: "smooth" });
    }, []);

    // 底纹词三档：已选 tag 时仅用短文案（"输入 #" 的提示已无意义）；否则由勾选状态
    // 决定问答范围的说法。部分浏览器不会随 React placeholder 属性刷新，需同步到 DOM
    const resolvedPlaceholder = selectedTag
        ? localize("com_knowledge.ai_input_placeholder_short")
        : selectedContent.length > 0
            ? localize("com_knowledge.ai_input_placeholder_selected")
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
        // Mobile: blur after sending so the keyboard dismisses and the grey overlay
        // (driven by focus → keyboardVisible) clears instead of lingering.
        if (isH5) textareaRef.current?.blur();
    }, [isStreaming, disabled, inputText, selectedTag, onSend, isH5]);

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

    const modelSelect = (
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
    );

    const sendControls = (
        <div className="flex shrink-0 items-center gap-2">
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
                    className="btn-brand-primary flex h-8 w-8 items-center justify-center rounded-full bg-primary text-text-primary outline-offset-4 transition-all duration-200"
                    onClick={onStop}
                    aria-label="Stop generating"
                >
                    <svg
                        width="18"
                        height="18"
                        viewBox="0 0 24 24"
                        fill="none"
                        xmlns="http://www.w3.org/2000/svg"
                        className="icon-lg text-surface-primary"
                    >
                        <rect x="7" y="7" width="10" height="10" rx="1.25" fill="currentColor" />
                    </svg>
                </button>
            ) : (
                <button
                    type="button"
                    onClick={handleSend}
                    disabled={disabled || !inputText.trim()}
                    className="btn-brand-primary flex h-8 w-8 items-center justify-center rounded-full bg-primary text-text-primary outline-offset-4 transition-all duration-200 disabled:cursor-not-allowed disabled:text-text-secondary disabled:opacity-10"
                    aria-label="Send message"
                    data-testid="send-button"
                >
                    <SendIcon size={18} />
                </button>
            )}
        </div>
    );

    return (
        <div
            className={cn(
                "relative flex w-full flex-col bg-white p-3",
                variant === "box"
                    ? "rounded-[20px] touch-mobile:rounded-2xl border border-[#E5E6EB] shadow-[0_2px_12px_rgba(0,0,0,0.06)]"
                    : "border-t border-[#EBEBEB]",
            )}
        >
            {/* Tag picker — floats above the input as a popover so single-row height stays compact */}
            {showPicker && (
                <div className="absolute bottom-full left-0 right-0 z-20 mb-2 px-3">
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

            {/* Reference row — the content ticked in the file list, in tick order.
                Always one line: it scrolls sideways rather than wrapping, so the
                input never grows taller as more content is picked. Nothing ticked →
                the row is absent, not empty, so no height is reserved for it. */}
            {!hideReferenceRow && selectedContent.length > 0 && (
                <div className="mb-2 flex w-full shrink-0 items-center gap-2">
                    {refCanLeft && <PagerButton direction="left" onClick={() => pageReferenceRow("left")} />}
                    <div className="relative min-w-0 flex-1">
                        <div
                            ref={referenceRowRef}
                            onScroll={updateReferenceEdges}
                            className="flex w-full gap-2 overflow-x-auto pb-1 scrollbar-on-scroll"
                        >
                            {selectedContent.map((item) => (
                                <AttachmentChip
                                    key={item.id}
                                    icon={
                                        item.isFolder ? (
                                            <Outlined.FolderClose size={16} />
                                        ) : (
                                            <KnowledgeChipFileIcon name={item.name} />
                                        )
                                    }
                                    label={item.name}
                                    className="h-8 bg-[#F8F8F8]"
                                    onRemove={onUnselectContent ? () => onUnselectContent(item.id) : undefined}
                                />
                            ))}
                        </div>
                        {/* Edge fades hinting at chips scrolled out of view (white surface). */}
                        <div
                            className={cn(
                                "pointer-events-none absolute left-0 top-0 h-full w-6 bg-gradient-to-r from-white from-[49%] to-transparent transition-opacity",
                                refCanLeft ? "opacity-100" : "opacity-0",
                            )}
                        />
                        <div
                            className={cn(
                                "pointer-events-none absolute right-0 top-0 h-full w-6 bg-gradient-to-l from-white from-[49%] to-transparent transition-opacity",
                                refCanRight ? "opacity-100" : "opacity-0",
                            )}
                        />
                    </div>
                    {refCanRight && <PagerButton direction="right" onClick={() => pageReferenceRow("right")} />}
                </div>
            )}

            <div className={cn("flex w-full", stacked ? "flex-col gap-2" : "items-center gap-2")}>
            {/* Single-row: model on the left, inline with the textarea. */}
            {!stacked && <div className="shrink-0">{modelSelect}</div>}

            {/* Textarea + tag badge. The badge overlays the first line; outer wrapper scrolls so the badge moves with text. */}
            <div className={cn(stacked ? "w-full" : "min-w-0 flex-1")}>
                <div ref={outerScrollRevealRef} className="max-h-48 overflow-y-auto overflow-x-hidden scrollbar-on-scroll">
                    <div className="relative">
                        {selectedTag && (
                            <span
                                ref={badgeRef}
                                className={`absolute left-0 top-0 z-10 box-border inline-flex h-5 max-h-5 min-h-5 max-w-[min(240px,90%)] shrink-0 items-center rounded-[2px] px-0 text-xs font-medium leading-none ${TAG_TEXT_CLASS} select-none transition-[background-color,box-shadow] duration-150 ease-out`}
                                style={{
                                    boxSizing: "border-box",
                                    backgroundColor: tagDeleteHighlight
                                        ? "rgb(var(--brand-500)/0.28)"
                                        : TAG_BG,
                                    boxShadow: tagDeleteHighlight
                                        ? "inset 0 0 0 1.5px rgb(var(--brand-500))"
                                        : "inset 0 0 0 1.5px rgb(var(--brand-500)/0)",
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
                            onFocus={() => onFocusChange?.(true)}
                            onBlur={() => onFocusChange?.(false)}
                            disabled={disabled || isStreaming}
                            placeholder={resolvedPlaceholder}
                            rows={1}
                            className="block w-full min-h-5 resize-none overflow-hidden bg-transparent text-sm leading-5 text-text-primary outline-none placeholder-[#86909c]"
                            style={{
                                textIndent: selectedTag ? `${badgeIndentPx ?? 0}px` : undefined,
                            }}
                            data-testid="knowledge-ai-input"
                        />
                    </div>
                </div>
            </div>

            {/* Controls. Single-row: mic + send pinned right. Stacked: model on the left, mic + send on the right. */}
            <div className={cn("flex items-center", stacked ? "w-full justify-between" : "shrink-0")}>
                {stacked && <div className="shrink-0">{modelSelect}</div>}
                {sendControls}
            </div>
            </div>
        </div>
    );
}
