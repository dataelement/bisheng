import { useEffect, useRef } from "react";
import DOMPurify from 'dompurify';
import { bindQuillEvent } from "@/util/utils";

export default function RichText({ msg }) {
    // scroll load
    const richTextRef = useRef<HTMLDivElement>(null)
    
    // 给富文本绑定事件（例如文件下载，图片展示）
    useEffect(() => {
        bindQuillEvent(richTextRef);
    }, [richTextRef])

    return <div dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(msg) }} ref={richTextRef} />
};
