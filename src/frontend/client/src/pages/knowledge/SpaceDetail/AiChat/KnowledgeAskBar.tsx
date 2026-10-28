/**
 * KnowledgeAskBar — desktop bottom bar of a knowledge space. It only TAKES the question:
 * sending hands it to the main chat (see ~/components/Chat/chatAskHandoff), which
 * opens a fresh conversation with this space mounted. The answer, and every later turn,
 * live on the 对话 page and in the workbench sidebar's conversation list — the space page
 * keeps no chat panel or history of its own on desktop.
 *
 * What does not carry over: the main chat scopes a question to whole spaces, so the
 * current folder and the `#` tag filter of the old in-place dock have no equivalent
 * there. The tag picker is therefore not offered here.
 *
 * Parent contract is the dock's: render inside a `position: relative` container; the bar
 * is `absolute inset-x-0 bottom-0` and overlays the bottom of the file list.
 */
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { parkChatAsk } from "~/components/Chat/chatAskHandoff";
import { useLocalize, useNewConvo } from "~/hooks";
import { useGetBsConfig } from "~/hooks/queries/endpoints/queries";
import { KnowledgeAiInput } from "./KnowledgeAiInput";

const NO_TAGS: { id: number; name: string }[] = [];
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

    const handleSend = (text: string) => {
        const question = text.trim();
        if (!question || !model) return;
        parkChatAsk({ text: question, modelId: Number(model.id), space: { id: spaceId, name: spaceName } });
        // Same pair the 新建对话 entry uses to land on an empty conversation.
        newConversation();
        navigate("/c/new");
    };

    return (
        <div className="pointer-events-none absolute inset-x-0 bottom-0 z-40 flex flex-col bg-gradient-to-b from-white/0 to-white px-4 pb-4 pt-10">
            <div className="pointer-events-auto relative mx-auto flex w-full max-w-[800px] flex-col">
                <KnowledgeAiInput
                    key={spaceId}
                    availableTags={NO_TAGS}
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
