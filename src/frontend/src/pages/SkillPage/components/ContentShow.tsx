import { Textarea } from "@/components/bs-ui/input"

export default function ContentShow({data}) {
    return <>
    <div className="bg-[white] pt-2 pl-3 pr-3">
        <div className="flex space-x-2 h-[20px] mt-4 mb-6">
            <span>审查类型：</span>
            <span>{data.reviewType}</span>
        </div>
        <div className="mt-4 mb-6 space-x-2">
            <span>词表类型：</span>
            <div className="inline">
                {data.vocabularyType?.map(v => <span className="mr-4">{v}</span>)}
            </div>
        </div>
        <span className="mb-4">自动回复内容</span>
        <div className="flex justify-center mt-4">
            <Textarea className="h-[100px] bg-[whitesmoke]" maxLength={500} value={data.automaticReply}
                placeholder="填写命中安全审查时的自动回复内容，例如“当前对话内容违反相关规范，请修改后重新输入"></Textarea>
        </div>
    </div>
    </>
}