/**
 * KnowledgeAskBar — desktop bottom bar of a knowledge space. It only TAKES the question:
 * sending hands it to the main chat (see ~/components/Chat/chatAskHandoff), which
 * opens a fresh conversation with this space mounted. The answer, and every later turn,
 * live on the 对话 page and in the workbench sidebar's conversation list — the space page
 * keeps no chat panel or history of its own on desktop.
 *
 * The current space and optional tag filter accompany the handoff. Folder scope
 * remains local to the mobile in-place dock.
 *
 * Parent contract is the dock's: render inside a `position: relative` container; the bar
 * is `absolute inset-x-0 bottom-0` and overlays the bottom of the file list.
 */
import { useCallback, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getSpaceTagsApi } from "~/api/knowledge";
import type { FolderChatTag } from "~/hooks/useFolderChat";
import { useNavigate } from "react-router-dom";
import { parkChatAsk } from "~/components/Chat/chatAskHandoff";
import { useLocalize, useNewConvo } from "~/hooks";
import { useGetBsConfig } from "~/hooks/queries/endpoints/queries";
import { KnowledgeAiInput } from "./KnowledgeAiInput";

const noop = () => undefined;

interface KnowledgeAskBarProps {
    spaceId: string;
    spaceName: string;
    /** Initial model inherited from the main chat. Picks belong to this draft. */
    modelValue?: number;
}

export function KnowledgeAskBar({ spaceId, spaceName, modelValue }: KnowledgeAskBarProps) {
    const navigate = useNavigate();
    const localize = useLocalize();
    const { data: bsConfig } = useGetBsConfig();
    const { newConversation } = useNewConvo(0);
    const [selectedModelId, setSelectedModelId] = useState(modelValue);
    const model = bsConfig?.models?.find((option) => String(option.id) === String(selectedModelId));
    const handleModelChange = (value: string) => setSelectedModelId(Number(value));

    const { data: tags = [], isFetching, isError, refetch } = useQuery({
        queryKey: ["spaceTags", spaceId],
        queryFn: () => getSpaceTagsApi(spaceId),
        enabled: !!spaceId,
        retry: false,
    });
    const refreshTags = useCallback(() => { void refetch(); }, [refetch]);
    const handleSend = (text: string, _files?: unknown[] | null, tag?: FolderChatTag) => {
        const question = text.trim();
        if (!question || !model) return;
        parkChatAsk({ text: question, modelId: Number(model.id), space: { id: spaceId, name: spaceName, ...(tag ? { tag } : {}) } });
        // Same pair the 新建对话 entry uses to land on an empty conversation.
        newConversation();
        navigate("/c/new");
    };

    return (
        <div className="pointer-events-none absolute inset-x-0 bottom-0 z-40 flex flex-col bg-gradient-to-b from-white/0 to-white px-4 pb-4 pt-10">
            <div className="pointer-events-auto relative mx-auto flex w-full max-w-[800px] flex-col">
                <KnowledgeAiInput
                    key={spaceId}
                    availableTags={tags}
                    tagsLoading={isFetching}
                    tagsError={isError}
                    onTagPickerOpen={refreshTags}
                    onRetryTags={refreshTags}
                    modelOptions={bsConfig?.models}
                    modelValue={selectedModelId}
                    onModelChange={handleModelChange}
                    onModelAutoChange={handleModelChange}
                    isStreaming={false}
                    disabled={!bsConfig?.models?.length}
                    onSend={handleSend}
                    onStop={noop}
                    variant="box"
                    placeholder={localize("com_knowledge.ask_bar_placeholder")}
                />
            </div>
        </div>
    );
}
