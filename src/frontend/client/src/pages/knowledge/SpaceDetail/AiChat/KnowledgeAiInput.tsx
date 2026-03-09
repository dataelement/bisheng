/**
 * KnowledgeAiInput — chat input for knowledge AI assistant.
 * Replaces the standard textarea with TagRichInput (contentEditable)
 * for inline tag capsule support. Reuses AiModelSelect for toolbar.
 *
 * Serialization: text "tag1" more text → sent to backend
 */
import { useCallback } from "react";
import { SendIcon } from "~/components/svg";
import AiModelSelect from "~/components/Chat/AiModelSelect";
import { TagRichInput } from "./TagRichInput";

interface KnowledgeAiInputProps {
    availableTags: string[];
    isStreaming: boolean;
    disabled?: boolean;
    bsConfig?: any;
    chatModel: any;
    onChatModelChange: (val: string) => void;
    onSend: (text: string, files?: any[] | null, tags?: string[]) => void;
    onStop: () => void;
    onNewChat: () => void;
}

export function KnowledgeAiInput({
    availableTags,
    isStreaming,
    disabled,
    bsConfig,
    chatModel,
    onChatModelChange,
    onSend,
    onStop,
}: KnowledgeAiInputProps) {

    const handleRichSend = useCallback((serialized: string, tags: string[]) => {
        if (isStreaming || disabled) return;
        onSend(serialized, null, tags.length > 0 ? tags : undefined);
    }, [isStreaming, disabled, onSend]);

    return (
        <div className="px-4 pb-4 shrink-0">
            <div className="relative pb-3 flex w-full flex-col bg-surface-tertiary rounded-xl">
                {/* Rich text editor with tag capsule support */}
                <TagRichInput
                    availableTags={availableTags}
                    disabled={disabled}
                    onSend={handleRichSend}
                />

                {/* Toolbar row */}
                <div className="relative h-8">
                    {/* Send / Stop */}
                    <div className="absolute bottom-0 right-3 flex gap-2 items-center">
                        {isStreaming ? (
                            <button
                                type="button"
                                className="rounded-full bg-primary p-1 text-text-primary outline-offset-4 transition-all duration-200"
                                onClick={onStop}
                                aria-label="Stop generating"
                            >
                                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" className="icon-lg text-surface-primary">
                                    <rect x="7" y="7" width="10" height="10" rx="1.25" fill="currentColor" />
                                </svg>
                            </button>
                        ) : (
                            <button
                                type="button"
                                onClick={() => {
                                    /* Send is handled by TagRichInput Enter key */
                                }}
                                disabled={disabled}
                                className="rounded-full bg-primary p-1 text-text-primary outline-offset-4 transition-all duration-200 disabled:cursor-not-allowed disabled:text-text-secondary disabled:opacity-10"
                                aria-label="Send message"
                                data-testid="send-button"
                            >
                                <SendIcon size={24} />
                            </button>
                        )}
                    </div>

                    {/* Model select */}
                    <div className="absolute bottom-0 left-3 flex gap-2 items-center">
                        {bsConfig?.models && (
                            <AiModelSelect
                                disabled={!!disabled}
                                value={chatModel.id}
                                options={bsConfig.models}
                                onChange={onChatModelChange}
                            />
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
}
