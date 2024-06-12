import { Textarea } from "@/components/bs-ui/input"

export default function FormView({ data }) {
    const map = { '1': '内置词表', '2': '自定义词表' }

    return <div className="mb-4 px-6">
            <div className="flex items-center mb-4">
                <span className="bisheng-label">审查类型：</span>
                <span>敏感词匹配</span>
            </div>
            <div className="flex items-center mb-4">
                <span className="bisheng-label">词表类型：</span>
                <div className="inline">
                    {data.wordsType?.map(v => <span className="mr-4">{map[v]}</span>)}
                </div>
            </div>
            <span  className="bisheng-label">自动回复内容：</span>
            <div className="flex justify-center mt-4">
                <p className="h-[100px] w-full bg-gray-50 py-2 px-4">{data.autoReply}</p>
            </div>
        </div>
}