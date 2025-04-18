import { Atom, ChevronRight } from "lucide-react";
import { useMemo, useState } from "react";
import { ThinkingButton } from "~/components/Artifacts/Thinking";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "~/components/ui";

const BUTTON_STYLES = {
    base: 'group mt-3 flex w-fit items-center justify-center rounded-xl bg-surface-tertiary px-3 py-2 text-xs leading-[18px] animate-thinking-appear',
    icon: 'icon-sm ml-1.5 transform-gpu text-text-primary transition-transform duration-200',
} as const;

export default function SearchWebUrls({ webs }) {
    const [isOpen, setIsOpen] = useState(false);

    return <div className="mb-4">
        <Dialog open={isOpen} onOpenChange={setIsOpen}>
            <DialogTrigger asChild>
                <button
                    type="button"
                    className={BUTTON_STYLES.base}
                    onClick={() => setIsOpen(true)}
                >
                    <Atom size={14} className="mr-1.5 text-text-secondary" />
                    已搜到 {webs.length} 个网页
                    <ChevronRight className="rotate-0 size-4" />
                </button>
            </DialogTrigger>

            <DialogContent className="absolute flex flex-col bottom-4 right-4 w-[440px] px-6 bg-white shadow-lg rounded-lg h-[92vh]">
                <DialogHeader className="text-md px-0">
                    <DialogTitle>搜索结果</DialogTitle>
                </DialogHeader>
                <div className="flex-1 pb-10 overflow-hidden flex flex-col">
                    <div className="flex-1 overflow-y-auto dark:text-gray-300">
                        {webs.map((web) => <WebItem key={web.url} {...web} />)}
                    </div>
                </div>
            </DialogContent>
        </Dialog>
    </div>
};

export const WebItem = ({ url, title, snippet }: { url: string; title: string; snippet: string }) => {
    // 清除文本中的 HTML 标签
    const stripHtmlTags = (text: string) => {
        const doc = new DOMParser().parseFromString(text, 'text/html');
        return doc.body.textContent || ''; // 获取纯文本内容
    };

    return (
        <div className="max-w-[440px]">
            <a href={url} target="_blank" className="block p-2 rounded-md hover:bg-gray-50 dark:hover:bg-gray-700 ">
                <div className="cursor-pointer">
                    {/* URL */}
                    <span className="text-sm text-gray-400">{url}</span>
                    {/* 标题加粗，清除 HTML 标签 */}
                    <h3 className="font-bold text-md mb-2">{stripHtmlTags(title)}</h3>
                    {/* 描述部分，最多两行，超出显示省略号，清除 HTML 标签 */}
                    <p className="text-sm text-gray-500 line-clamp-2">
                        {stripHtmlTags(snippet)}
                    </p>
                </div>
            </a>
        </div>
    );
};

