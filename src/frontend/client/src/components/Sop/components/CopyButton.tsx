import { useState, useRef, useEffect } from "react";
import { Button } from "~/components/ui";
import { Tooltip, TooltipContent, TooltipTrigger } from "../../ui/tooltip2";
import { Copy, CopyCheck } from "lucide-react";

export default function CopyButton({ text }: { text: string }) {
    const [copied, setCopied] = useState(false);
    const timeoutRef = useRef<NodeJS.Timeout | null>(null);

    // 清理定时器
    useEffect(() => {
        return () => {
            if (timeoutRef.current) {
                clearTimeout(timeoutRef.current);
            }
        };
    }, []);

    const handleCopy = () => {
        try {
            // 方法1: 使用现代 Clipboard API
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(text).then(() => {
                    setCopiedState();
                }).catch(() => {
                    fallbackCopyText(text);
                });
            }
            // 方法2: 使用旧版 document.execCommand
            else {
                fallbackCopyText(text);
            }
        } catch (err) {
            console.error("复制失败:", err);
        }
    };

    const fallbackCopyText = (textToCopy: string) => {
        // 创建临时 textarea 元素作为复制后备方案
        const textArea = document.createElement("textarea");
        textArea.value = textToCopy;
        textArea.style.position = "fixed";
        textArea.style.top = "0";
        textArea.style.left = "0";
        textArea.style.opacity = "0";

        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();

        try {
            const successful = document.execCommand("copy");
            if (successful) {
                setCopiedState();
            } else {
                console.error("复制命令失败");
            }
        } catch (err) {
            console.error("复制失败:", err);
        } finally {
            document.body.removeChild(textArea);
        }
    };

    const setCopiedState = () => {
        setCopied(true);
        if (timeoutRef.current) {
            clearTimeout(timeoutRef.current);
        }
        timeoutRef.current = setTimeout(() => setCopied(false), 2000);
    };

    return (
        <Tooltip disableHoverableContent>
            <TooltipTrigger asChild>
                <Button
                    variant="ghost"
                    size="icon"
                    className="size-8 p-1.5 hover:bg-accent/50"
                    onClick={handleCopy}
                    aria-label={copied ? "已复制" : "复制到剪贴板"}
                >
                    {copied ? (
                        <CopyCheck size={16} className="text-primary" />
                    ) : (
                        <Copy size={16} />
                    )}
                </Button>
            </TooltipTrigger>
            <TooltipContent side="top" align="center">
                <p>{copied ? "已复制!" : "复制"}</p>
            </TooltipContent>
        </Tooltip>
    );
}