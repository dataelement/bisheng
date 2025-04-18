import FileView from "@/components/bs-comp/FileView";
import { generateUUID } from "@/components/bs-ui/utils";
import React, { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

export default function FileViewPanne({ file }) {
    const { t } = useTranslation()
    const MemoizedFileView = React.memo(FileView);
    const [postion, setPositon] = useState(null)
    const [currentIndex, setCurrentIndex] = useState(0)

    const labels = useMemo(() => {
        const map = {}
        file.chunks.forEach(chunk => {
            chunk.box.forEach(el => {
                if (!map[el.page]) {
                    map[el.page] = []
                }
                map[el.page].push({ id: generateUUID(8), label: el.bbox, active: true, txt: '' })
            })
        })
        console.log('file.chunks[0].box[0].page :>> ', file.chunks);
        setPositon([file.chunks[0].box[0].page, file.chunks[0].box[0].bbox[1] || 0])
        return map
    }, [file.chunks])

    const handleJump = (i: number, chunk: typeof file.chunks[number]) => {
        setCurrentIndex(i)
        //postion: [page, label[1] + random] : null
        const random = Math.random() / 100 // 随机偏移量
        setPositon([chunk.box[0].page, chunk.box[0].bbox[1] || 0 + random])
    }

    return <div className="flex-1 bg-gray-100 rounded-md py-4 px-2 relative" onContextMenu={(e) => e.preventDefault()}>
        <MemoizedFileView scrollTo={postion} fileUrl={file.fileUrl} labels={labels} />
        {/* chunk menu */}
        <div className="absolute left-[0px] rounded-sm p-4 px-0 top-[50%] translate-y-[-50%] max-2xl:scale-75 origin-top-left">
            <p className="mb-1 text-sm font-bold text-center rounded-sm bg-[rgb(186,210,249)] text-blue-600">{t('chat.sourceTooltip')}</p>
            <div className="flex flex-col gap-2 ">
                {file.chunks.map((chunk, i) =>
                    <div key={i}
                        onClick={() => handleJump(i, chunk)}
                        className={`flag h-[38px] leading-[38px] px-6 pl-4 border-2 border-l-0 border-r-0 border-[rgba(53,126,249,.60)] bg-[rgba(255,255,255,0.2)]  text-blue-600 ${currentIndex === i && 'font-bold active'} cursor-pointer relative`}
                    >
                        <span>{chunk.score}</span>
                    </div>
                )}
            </div>
        </div>
    </div>
};
