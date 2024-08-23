import { LoadIcon } from "@/components/bs-icons";
import { Button } from "@/components/bs-ui/button";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { Crosshair2Icon, InfoCircledIcon } from "@radix-ui/react-icons";
import React, { useCallback, useMemo, useRef, useState } from 'react';
import { useParams } from "react-router-dom";
import FileView from "./FileView";
import Markdown from './Markdown';

export default function ParagraphEdit({ id, onClose }) {
    const param = useParams();
    const fileId = param['fileid'];
    const v = `# Milkdown React Commonmark

    > You're scared of a world where you're needed.
    
    This is a demo for using Milkdown with **React**.

|  表头   | 表头  |
|  ----  | ----  |
| 单元格  | 单元格 |
| 单元格  | 单元格 |
`
    const [value, setValue] = useState(v);

    const markDownRef = useRef(null)
    const { leftPanelWidth, handleMouseDown } = useDragSize(false)
    const [labelChange, setLabelChange] = useState(false)
    const { message } = useToast()

    // const [error, setError] = useState(false)
    const [loading, setLoading] = useState(false)
    const handleSave = () => {
        const _value = markDownRef.current.getValue().trim()
        setValue(_value)
        console.log('save :>> ', _value);
        if (!_value) return
        setLoading(true)
        setTimeout(() => {
            setLoading(false)
            message({ variant: 'success', description: '修改成功' })
            onClose()
        }, 2000);
    }
    const fileUrl = 'http://192.168.106.116:9000/bisheng/33407?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=minioadmin%2F20240820%2Fus-east-1%2Fs3%2Faws4_request&X-Amz-Date=20240820T115721Z&X-Amz-Expires=604800&X-Amz-SignedHeaders=host&X-Amz-Signature=3c943f2951f04e98d258fd567f43acc32b691769668e0ea0cbb2464c0febb4f6'
    const [data, setData] = useState([
        { page: 1, label: [89, 194, 440, 210], active: false, txt: 'xx' },
        { page: 1, label: [89, 794, 440, 810], active: true, txt: 'zz' },
        { page: 2, label: [189, 194, 440, 210], active: true, txt: 'yy' },
        { page: 2, label: [189, 294, 440, 310], active: false, txt: 'ww' }
    ])

    const labels = useMemo(() => {
        return data.reduce((acc, item) => {
            if (!acc[item.page]) {
                acc[item.page] = [];
            }
            acc[item.page].push({ id: item.txt, ...item });

            return acc;
        }, {});
    }, [data]);

    const handleSelectLabels = (lbs) => {
        let arr = data
        lbs.forEach((item) => {
            arr = arr.map(el => el.txt === item.id ? { ...el, active: item.active } : el)
        })
        setData(arr)
        console.log('arr :>> ', lbs, arr);

        setLabelChange(true)
    }

    const handleOvergap = () => {
        setLabelChange(false)
        const _value = data.reduce((str, item) => {
            if (item.active) {
                str += item.txt + '\n'
            }
            return str
        }, '')
        setValue(_value)
    }

    // 定位到最前一个激活的标签
    const [random, setRandom] = useState(0)
    const postion = useMemo(() => {
        const target = data.find(el => el.active)
        return target ? [target.page, target.label[1] + random] : null
    }, [random])

    return (
        <div className="flex px-4 py-2 select-none">
            <div className="relative" style={{ width: leftPanelWidth }}>
                <div className="flex justify-between h-10 items-center mb-2">
                    <span>讲座实录.docx</span>
                    <span># 2</span>
                </div>
                <Markdown ref={markDownRef} value={value} />
                {!value && <p className="absolute left-0 text-red-500 text-xs mt-2">输入内容不可为空</p>}
                <div className="flex justify-end gap-4">
                    <Button className="px-6" variant="outline" onClick={onClose}>取消</Button>
                    <Button className="px-6" disabled={loading} onClick={handleSave}><LoadIcon className={`mr-1 ${loading ? '' : 'hidden'}`} />保存</Button>
                </div>
            </div>
            <>
                <div className="h-full p-2">
                    <div
                        className="h-full w-1 border cursor-ew-resize"
                        onMouseDown={handleMouseDown}
                    ></div>
                </div>
                <div className="flex-1">
                    <div className="flex items-center relative h-10 mb-2 text-sm">
                        <div className={`${labelChange ? '' : 'hidden'} flex items-center`}>
                            <InfoCircledIcon className='mr-1' />
                            <span>检测到分段范围调整,</span>
                            <span className="text-primary cursor-pointer" onClick={handleOvergap}>覆盖分段内容</span>
                        </div>
                        {/* <Button variant="ghost" className="absolute right-0" size="icon" onClick={() => navigate(-1)}><Cross1Icon /></Button> */}
                    </div>
                    <div className="bg-gray-100 relative">
                        {value && Object.keys(labels).length && <Button className="absolute top-2 right-2 z-10" variant="outline" onClick={() => setRandom(Math.random() / 10000)}><Crosshair2Icon className="mr-1" />回到定位</Button>}
                        <div className="h-[calc(100vh-72px)]">
                            <FileView fileUrl={fileUrl} labels={labels} scrollTo={postion} onSelectLabel={handleSelectLabels} />
                        </div>
                    </div>
                </div>
            </>
        </div>
    );
};

const useDragSize = (full) => {
    // State for the left panel width
    const [leftPanelWidth, setLeftPanelWidth] = useState(full ? '100%' : window.innerWidth * 0.4);
    const [isDragging, setIsDragging] = useState(false);

    const handleMouseDown = useCallback(() => {
        setIsDragging(true);
    }, []);

    const handleMouseUp = useCallback(() => {
        setIsDragging(false);
    }, []);

    const handleMouseMove = useCallback(
        (e) => {
            if (isDragging) {
                // Calculate the new width
                const newWidth = e.clientX - 24;
                if (newWidth >= 320 && newWidth <= window.innerWidth * 0.7) { // Limiting the width between 320px and full width * 70%
                    setLeftPanelWidth(newWidth);
                }
            }
        },
        [isDragging]
    );

    React.useEffect(() => {
        if (full) return
        if (isDragging) {
            window.addEventListener('mousemove', handleMouseMove);
            window.addEventListener('mouseup', handleMouseUp);
        } else {
            window.removeEventListener('mousemove', handleMouseMove);
            window.removeEventListener('mouseup', handleMouseUp);
        }

        return () => {
            window.removeEventListener('mousemove', handleMouseMove);
            window.removeEventListener('mouseup', handleMouseUp);
        };
    }, [full, isDragging, handleMouseMove, handleMouseUp]);

    return { leftPanelWidth, handleMouseDown };
}