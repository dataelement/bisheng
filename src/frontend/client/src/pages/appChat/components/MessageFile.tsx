import { MessageImage } from "~/components/Chat/Messages/Content/MessageImage"
import { isImageFileName } from "~/components/ui/icon/File/FileIcon"
import { formatStrTime } from "~/utils"
import ChatFile from "./ChatFile"

export default function MessageFile({ data, title, logo }) {
    const files = data.files || []

    return <div className="flex w-full">
        <div className="w-fit group max-w-[90%]">
            <div className="flex justify-between items-center mb-1">
                {data.sender ? <p className="text-gray-600 text-xs">{data.sender}</p> : <p />}
                <div className={`text-right group-hover:opacity-100 opacity-0`}>
                    <span className="text-slate-400 text-sm">{formatStrTime(data.create_time, 'MM 月 dd 日 HH:mm')}</span>
                </div>
            </div>
            <div className="min-h-8 px-4 py-2">
                <div className="flex gap-3">
                    {logo}
                    <div>
                        <p className="select-none font-semibold text-base mb-2">{title}</p>
                        {/* Pictures show as pictures; anything else stays the
                            download card it has always been. */}
                        <div className="flex flex-wrap gap-2">
                            {files.map((file, i) => {
                                const fileName = file.file_name || file.filename
                                return isImageFileName(fileName)
                                    ? <MessageImage
                                        key={file.file_id ?? i}
                                        conversationId={data.chat_id}
                                        fileId={file.file_id}
                                        altText={fileName}
                                    />
                                    : <ChatFile key={file.file_id ?? i} fileName={fileName} filePath={file.file_url} />
                            })}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div >
};
