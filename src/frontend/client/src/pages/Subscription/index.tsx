import { useEffect, useState } from "react";
import { Article, Channel } from "~/api/channels";
import { NotificationSeverity } from "~/common";
import { useToastContext } from "~/Providers";
import ChannelSquare from "../ChannelSquare";
import { ChannelLayout } from "./ChannelLayout";
import FullScreenArticle from "./Article/FullScreenArticle";
import { ChannelSidebar } from "./sidebar/ChannelSidebar";

export default function Subscription() {
    const [activeChannel, setActiveChannel] = useState<Channel | null>(null);
    const [showChannelSquare, setShowChannelSquare] = useState(false);
    const [fullScreenArticle, setFullScreenArticle] = useState<Article | null>(null);
    const [showAiAssistant, setShowAiAssistant] = useState(false);
    const { showToast } = useToastContext();

    // Handle channel selection
    const handleChannelSelect = (channel: Channel | null) => {
        setActiveChannel(channel);
    };

    // Create channel
    const handleCreateChannel = () => {
        showToast({
            message: "创建频道功能开发中",
            severity: NotificationSeverity.INFO
        });
    };

    // Channel square
    const handleChannelSquare = () => {
        setShowChannelSquare(true);
    };

    // Esc to exit full screen
    useEffect(() => {
        if (!fullScreenArticle) return;
        const onKeyDown = (e: KeyboardEvent) => {
            if (e.key === "Escape") setFullScreenArticle(null);
        };
        window.addEventListener("keydown", onKeyDown);
        return () => window.removeEventListener("keydown", onKeyDown);
    }, [fullScreenArticle]);

    return (
        <div className="relative h-full flex">
            {showChannelSquare ? (
                <ChannelSquare onBack={() => setShowChannelSquare(false)} />
            ) : (
                <>
                    {/* left sidebar */}
                    <ChannelSidebar
                        activeChannelId={activeChannel?.id}
                        onChannelSelect={handleChannelSelect}
                        onCreateChannel={handleCreateChannel}
                        onChannelSquare={handleChannelSquare}
                    />

                    {activeChannel ? (
                        <ChannelLayout
                            channel={activeChannel}
                            onFullScreen={(article, ai) => {
                                setFullScreenArticle(article);
                                setShowAiAssistant(ai || false);
                            }}
                        />
                    ) : (
                        <div className="flex flex-1 flex-col items-center justify-center py-10 text-center">
                            <img
                                className="size-[120px] mb-4 object-contain opacity-90"
                                src={`${__APP_ENV__.BASE_URL}/assets/channel/empty.png`}
                                alt="empty"
                            />
                            <p className="text-[14px] leading-6 text-[#4E5969]">
                                无相关内容，请
                                <span
                                    className="ml-1.5 cursor-pointer text-[#165DFF] transition-colors hover:text-[#4080FF] active:text-[#0E42D2]"
                                    onClick={handleCreateChannel}
                                >
                                    创建频道
                                </span>
                            </p>
                        </div>
                    )}
                </>
            )}

            {/* Full-screen overlay — absolute inset-0 covers the entire Subscription (including the channel sidebar), but doesn't affect MainLayout's primary navigation */}
            {fullScreenArticle && (
                <div className="absolute inset-0 z-50 bg-white flex flex-col h-full">
                    <FullScreenArticle
                        onExit={() => {
                            setFullScreenArticle(null);
                            setShowAiAssistant(false);
                        }}
                        article={fullScreenArticle}
                        showAiAssistant={showAiAssistant}
                        setShowAiAssistant={setShowAiAssistant}
                    />
                </div>
            )}
        </div>
    );
}
