/**
 * ArticleAskBar — desktop bottom bar of a channel article. Like the knowledge space's
 * KnowledgeAskBar it only TAKES the question: sending hands it to the main chat (see
 * ~/components/Chat/chatAskHandoff), which opens a fresh conversation. The daily chat has
 * no handle for "this article", so the article rides along as a Markdown attachment
 * (articleAskFile) and the question is sent once the chat has uploaded and parsed it.
 * The answer and every later turn live on the 对话 page and in the workbench sidebar's
 * conversation list — the article page keeps no chat panel or history on desktop.
 *
 * Parent contract is the dock's: render inside a `position: relative` container; the bar
 * is `absolute inset-x-0 bottom-0` and overlays the bottom of the article.
 */
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import type { Article } from "~/api/channels";
import { parkChatAsk } from "~/components/Chat/chatAskHandoff";
import { useLocalize, useNewConvo } from "~/hooks";
import { buildArticleAskFile } from "./articleAskFile";
import { DockInput, type ModelSelectProps } from "./ArticleDockInput";

interface ArticleAskBarProps {
    article: Article;
    /** Model select wiring — owned by the caller, which may read the shared chat-model state. */
    model: ModelSelectProps;
}

export function ArticleAskBar({ article, model }: ArticleAskBarProps) {
    const localize = useLocalize();
    const navigate = useNavigate();
    const { newConversation } = useNewConvo(0);
    const [inputText, setInputText] = useState("");

    const handleSend = (text: string) => {
        parkChatAsk({
            text,
            attachment: buildArticleAskFile(article, {
                source: localize("com_subscription.ask_file_source"),
                link: localize("com_subscription.ask_file_link"),
                publishedAt: localize("com_subscription.ask_file_published_at"),
            }),
        });
        setInputText("");
        // Same pair the 新建对话 entry uses to land on an empty conversation.
        newConversation();
        navigate("/c/new");
    };

    return (
        <div className="pointer-events-none absolute inset-x-0 bottom-0 z-40 flex flex-col bg-gradient-to-b from-white/0 to-white px-4 pb-4 pt-10">
            <div className="pointer-events-auto mx-auto w-full max-w-[800px]">
                <DockInput
                    value={inputText}
                    onChange={setInputText}
                    onSend={handleSend}
                    model={model}
                    disabled={!model.options?.length}
                    isStreaming={false}
                    placeholder={localize("com_subscription.ask_bar_placeholder")}
                    variant="box"
                />
            </div>
        </div>
    );
}
