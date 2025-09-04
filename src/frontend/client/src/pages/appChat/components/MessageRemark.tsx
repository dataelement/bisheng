import Markdown from "~/components/Chat/Messages/Content/Markdown";

// 开场白
export default function MessageRemark({ logo, title, message }:
    { logo: React.ReactNode, title: string, message: string }) {

    return <div className="flex w-full">
        <div className="w-fit group max-w-[90%]">
            <div className="min-h-8 px-6 pt-4 pb-2 rounded-2xl">
                <div className="flex gap-2">
                    {logo}
                    <div className="text-sm max-w-[calc(100%-24px)]">
                        <p>{title}</p>
                        <div className="bs-mkdown text-sm mt-2"><Markdown content={message} isLatestMessage={false} webContent={undefined} /></div>
                    </div>
                </div>
            </div>
        </div>
    </div>
};
