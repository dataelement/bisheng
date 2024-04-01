import { useMemo } from "react"
import ReactMarkdown from "react-markdown"

export default function MessageSystem({ data }) {

    // 日志markdown
    const logMkdown = useMemo(
        () => (
            data.thought && <ReactMarkdown
                linkTarget="_blank"
                className="markdown text-gray-600 inline-block break-all max-w-full text-sm [&>pre]:text-wrap"
            >
                {data.thought.toString()}
            </ReactMarkdown>
        ),
        [data.thought]
    )

    const border = { system: 'border-slate-500', question: 'border-amber-500', processing: 'border-cyan-600', answer: 'border-lime-600', report: 'border-slate-500' }
    const color = { system: 'bg-slate-50', question: 'bg-slate-50', processing: 'bg-slate-50', answer: 'bg-slate-50', report: 'bg-slate-50' }

    return <div className="py-1">
        <div className={`rounded-sm px-6 py-4 border text-sm bg-slate-50 ${border[data.category || 'system']}`}>
            {logMkdown}
        </div>
    </div>
};
