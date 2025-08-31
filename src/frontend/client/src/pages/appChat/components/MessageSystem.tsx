import { Copy } from "lucide-react";
import { useMemo } from "react";
import Markdown from "~/components/Chat/Messages/Content/Markdown";
import { useToastContext } from "~/Providers";
import { copyText } from "~/utils";

export default function MessageSystem({ data }) {
    const { showToast } = useToastContext();

    const handleCopy = (dom) => {
        copyText(dom)

        showToast({ message: '内容已复制', status: 'success' });
    }

    // 日志markdown
    const logMkdown = useMemo(
        () => (
            data.thought && <Markdown content={data.thought.toString()} isLatestMessage={false} webContent={undefined} />
        ),
        [data.thought]
    )

    const border = { system: 'border-slate-500', question: 'border-amber-500', processing: 'border-cyan-600', answer: 'border-lime-600', report: 'border-slate-500', guide: 'border-none' }

    return <div className="py-1">
        <div className={`relative rounded-sm px-6 py-4 border text-sm dark:bg-gray-900 ${data.category === 'guide' ? 'bg-[#EDEFF6]' : 'bg-slate-50'} ${border[data.category || 'system']}`}>
            {logMkdown}
            {data.category === 'report' && <Copy className=" absolute right-4 top-2 cursor-pointer" onClick={(e) => handleCopy(e.target.parentNode)}></Copy>}
        </div>
    </div>
};
