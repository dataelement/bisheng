import { useToast } from "@/components/bs-ui/toast/use-toast"
import { copyText } from "@/utils"
import { Copy } from "lucide-react"
import { useMemo } from "react"
import { useTranslation } from "react-i18next"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"

export default function MessageSystem({ data }) {
    const { message } = useToast()
    const { t } = useTranslation()

    const handleCopy = (dom) => {
        copyText(dom)

        message({
            variant: 'success',
            title: t('prompt'),
            description: t('chat.copyTip')
        })
    }

    // 日志markdown
    const logMkdown = useMemo(
        () => (
            data.thought && <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                linkTarget="_blank"
                className="bs-mkdown text-gray-600 dark:text-[white] inline-block break-all max-w-full text-sm [&>pre]:text-wrap"
            >
                {data.thought.toString()}
            </ReactMarkdown>
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
