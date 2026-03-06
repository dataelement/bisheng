import {
    ArrowUp,
    Copy,
    Download,
    X,
    ZoomIn,
    ZoomOut
} from "lucide-react";

import { useEffect, useRef, useState } from "react";
import { Article } from "~/api/channels";
import { AddToKnowledgeModal } from "./AddToKnowledgeModal";
import { OriginalWebIcon, ShareOutlineIcon, AddSpaceIcon, FullScreenIcon, AiChatIcon } from "~/components/icons";
import { useToastContext } from "~/Providers";
import { copyText } from "~/utils";
import { Separator } from "~/components";

interface ArticleDetailProps {
    article: Article;
    screenFull?: boolean;
    aiAssistantOpen?: boolean;
    onFullScreen?: () => void;
    onExitAiAssistant?: () => void;
    onAiAssistant?: () => void;
}

const html = `<article>
    <h1>2025年北京PM2.5年均浓度首破“30微克”</h1>
    <p>元旦假期，天坛公园上空万里无云，澄澈蓝天之下游客人如织。</p>
    
    <img src="http://192.168.2.224:4001/workspace/bisheng/icon/f31edaaeb8e9406085bf8c270cb2af63.png?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=minioadmin%2F20260226%2Fus-east-1%2Fs3%2Faws4_request&X-Amz-Date=20260226T142350Z&X-Amz-Expires=604800&X-Amz-SignedHeaders=host&X-Amz-Signature=0b077cc95e4c21959000e6b1446ada908b4ed1c2723dd70e9c6e716e2518d285" alt="天坛风景" />
    
    <p>1月4日上午，北京市人民政府新闻办公室举行北京市空气质量状况新闻发布会...</p>
    <p style="margin-top: 1000px;">这里故意增加间距，用于测试“回到顶部”按钮出现的情况...</p>
    <img src="https://example.com/images/chart.png" alt="数据图表" />
    
    <p>多项指标创有监测以来最优。PM2.5优良天数达348天，占比95.3%。</p>
</article>`

export function ArticleDetail({ article, screenFull = false, aiAssistantOpen = false, onFullScreen, onExitAiAssistant, onAiAssistant }: ArticleDetailProps) {
    const [previewUrl, setPreviewUrl] = useState<string | null>(null);
    const [scale, setScale] = useState(1);
    const [showBackTop, setShowBackTop] = useState(false);
    const [showKnowledgeModal, setShowKnowledgeModal] = useState(false);
    const iframeRef = useRef<HTMLIFrameElement>(null);
    const { showToast } = useToastContext();

    const processedHtml = `
    <html>
      <head>
        <style>
          html{scrollbar-width: none;}
          body { font-family: sans-serif; line-height: 1.6; color: #333; padding: 20px; scroll-behavior: smooth; }
          img { max-width: 100%; cursor: zoom-in; }
        </style>
      </head>
      <body>
        ${html}
       <script>
          // Image click
          document.querySelectorAll('img').forEach(img => {
            img.onclick = (e) => window.parent.postMessage({ type: 'IMAGE_PREVIEW', url: e.target.src }, '*');
          });

          // Scroll listener: inform parent whether to show "Back to Top"
          window.onscroll = () => {
            const shouldShow = window.pageYOffset > window.innerHeight;
            window.parent.postMessage({ type: 'SCROLL_STATUS', show: shouldShow }, '*');
          };

          // Receive parent command: scroll back to top
          window.addEventListener('message', (e) => {
            if (e.data.type === 'DO_SCROLL_TOP') window.scrollTo({ top: 0, behavior: 'smooth' });
          });
        </script>
      </body>
    </html>
  `;

    useEffect(() => {
        const handleMessage = (event: MessageEvent) => {
            if (event.data.type === 'IMAGE_PREVIEW') {
                setPreviewUrl(event.data.url);
                setScale(1); // Reset scale
            }
            if (event.data.type === 'SCROLL_STATUS') {
                setShowBackTop(event.data.show);
            }
        };
        window.addEventListener("message", handleMessage);
        return () => window.removeEventListener("message", handleMessage);
    }, []);

    // --- Image operation logic ---
    const handleDownload = async () => {
        if (!previewUrl) return;
        const res = await fetch(previewUrl);
        const blob = await res.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `image-${Date.now()}.png`;
        a.click();
    };

    const handleCopy = async () => {
        if (!previewUrl) return;
        try {
            const data = await fetch(previewUrl);
            const blob = await data.blob();
            await navigator.clipboard.write([new ClipboardItem({ [blob.type]: blob })]);
            alert("Image copied to clipboard");
        } catch (err) {
            console.log('err :>> ', err);
            // Fallback: copy link only
            await navigator.clipboard.writeText(previewUrl);
            alert("Failed to copy image, copied link instead");
        }
    };

    const handleBackToTop = () => {
        iframeRef.current?.contentWindow?.postMessage({ type: 'DO_SCROLL_TOP' }, '*');
    };

    const handleFullScreen = () => {
        onFullScreen?.()
    }

    const handleShare = () => {
        const shareText = `我正在阅读【${article.title}】${article.url}`;
        copyText(shareText).then(() => {
            showToast({ message: '分享链接已复制到粘贴板', status: 'success' });
        }).catch(() => {
            showToast({ message: '复制失败，请重试', status: 'error' });
        });
    }

    const hasKnowledge = true
    return (
        <div className={`flex px-4 py-5 flex-col h-full  ${screenFull ? '' : 'border-l border-gray-100'}`}>
            {/* Top Toolbar */}
            <div className="border-b border-black pb-4">
                <div className="flex items-start justify-between">
                    <h2 className="font-semibold leading-relaxed flex-1 font-[serif]">
                        {article.title}
                    </h2>
                </div>

                <div className="flex items-center justify-between pt-2">
                    <div className="w-full h-6 flex items-center gap-4">
                        <button
                            onClick={() => window.open(article.url)}
                            className="flex items-center gap-1 text-xs transition-colors text-gray-900"
                        >
                            <OriginalWebIcon className="size-3.5" />
                            原网页
                        </button>

                        <button
                            className="flex items-center gap-1 text-xs transition-colors text-gray-900"
                            onClick={handleShare}
                        >
                            <ShareOutlineIcon className="size-3.5 text-[#94BFFF]" />
                            分享
                        </button>

                        {hasKnowledge && <button
                            className="flex items-center gap-1 text-xs transition-colors text-gray-900"
                            onClick={() => setShowKnowledgeModal(true)}
                        >
                            <AddSpaceIcon className="size-3.5" />
                            加入知识空间
                        </button>}

                        {(!screenFull || (screenFull && aiAssistantOpen)) && <button
                            className="flex items-center gap-1 text-xs transition-colors text-gray-900"
                            onClick={() => {
                                if (screenFull && aiAssistantOpen && onExitAiAssistant) {
                                    onExitAiAssistant();
                                } else {
                                    onFullScreen?.();
                                }
                            }}
                        >
                            <FullScreenIcon className="size-3.5" />
                            全屏
                        </button>}

                        <div className="ml-auto">
                            {/* <div className="flex items-center gap-3 text-[14px] antialiased">
                                <div className="flex-shrink-0">
                                    <svg
                                        width="18"
                                        height="18"
                                        viewBox="0 0 24 24"
                                        fill="none"
                                        className="text-[#e60012]" 
                                        xmlns="http://www.w3.org/2000/svg"
                                    >
                                        <path
                                            d="M12 2L4 7V17L12 22L20 17V7L12 2Z"
                                            stroke="currentColor"
                                            strokeWidth="2"
                                            strokeLinecap="round"
                                            strokeLinejoin="round"
                                        />
                                        <circle cx="12" cy="12" r="3" fill="currentColor" />
                                    </svg>
                                </div>
                                <span className="font-medium text-slate-800 tracking-tight">
                                    北京日报
                                </span>
                                <Separator orientation="vertical" className="h-4 bg-slate-200" />
                                <span className="text-slate-400 font-normal tabular-nums">
                                    2026-01-05 08:22
                                </span>
                            </div> */}
                            <button
                                className="flex items-center gap-1 text-xs transition-colors bg-gradient-to-br from-[#335CFF] to-[#7433FF] bg-clip-text text-transparent"
                                onClick={() => onAiAssistant?.()}
                            >
                                <AiChatIcon className="size-3.5 text-primary" />
                                AI 问答
                            </button>
                        </div>
                    </div>
                </div>
            </div>

            {/* Iframe Content Area */}
            <div className="flex-1 bg-white relative">
                <iframe
                    ref={iframeRef}
                    srcDoc={processedHtml}
                    className="w-full h-full border-none"
                />

                {/* Back to Top Button */}
                {showBackTop && (
                    <button
                        onClick={handleBackToTop}
                        className="absolute bottom-8 right-8 size-10 bg-white shadow-lg border border-[#e5e6eb] rounded-full flex items-center justify-center text-[#4e5969] hover:text-primary transition-all animate-in fade-in slide-in-from-bottom-4"
                    >
                        <ArrowUp className="size-5" />
                    </button>
                )}
            </div>

            {/* 3. Image Preview Overlay */}
            {previewUrl && (
                <div className="fixed inset-0 z-[999] bg-black/90 flex flex-col items-center justify-center">
                    {/* Top Action Bar */}
                    <div className="absolute top-0 w-full flex justify-between p-6 text-white/80">
                        <div className="flex items-center gap-6">
                            <button onClick={() => setScale(s => s + 0.2)} className="hover:text-white flex items-center gap-1">
                                <ZoomIn className="size-5" /> 放大
                            </button>
                            <button onClick={() => setScale(s => Math.max(0.5, s - 0.2))} className="hover:text-white flex items-center gap-1">
                                <ZoomOut className="size-5" /> 缩小
                            </button>
                            <div className="w-px h-4 bg-white/20 mx-2" />
                            <button onClick={handleCopy} className="hover:text-white flex items-center gap-1">
                                <Copy className="size-5" /> 复制
                            </button>
                            <button onClick={handleDownload} className="hover:text-white flex items-center gap-1">
                                <Download className="size-5" /> 下载
                            </button>
                        </div>
                        <button onClick={() => setPreviewUrl(null)} className="hover:text-white text-white bg-white/10 p-2 rounded-full">
                            <X className="size-8" />
                        </button>
                    </div>

                    {/* Image Body */}
                    <div className="overflow-auto max-w-full max-h-full flex items-center justify-center p-10 cursor-grab active:cursor-grabbing">
                        <img
                            src={previewUrl}
                            style={{ transform: `scale(${scale})`, transition: 'transform 0.2s cubic-bezier(0.4, 0, 0.2, 1)' }}
                            className="max-w-[85vw] max-h-[85vh] object-contain shadow-2xl"
                            alt="Preview"
                        />
                    </div>
                </div>
            )}

            {/* Add to Knowledge Space Modal */}
            <AddToKnowledgeModal
                open={showKnowledgeModal}
                onOpenChange={setShowKnowledgeModal}
            />
        </div>
    );
}