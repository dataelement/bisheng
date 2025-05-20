import { forwardRef, useEffect, useImperativeHandle, useRef, useState, useMemo } from "react";
import { FileIcon } from "@/components/bs-icons/file";
import {
    Select,
    SelectContent,
    SelectGroup,
    SelectItem,
    SelectLabel,
    SelectTrigger,
    SelectValue,
} from "@/components/bs-ui/select";
interface YuLanProps {
    fileNames: string[];
}
export default function YuLan({ fileNames }: YuLanProps) {
    console.log(fileNames, '----------');

    const [abc, setAbc] = useState([
        "这是第一段文本内容。React 是一个用于构建用户界面的构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J构建用户界面的 J JavaScript 库，它可以帮助你轻松创建交互式 UI。",
        "第二段文本示例。组件化是 React 的核心思想之一，允许你将 UI 拆分为独立可复用的代码片段。",
        "接下来是第三段。在 React 中，props 是父组件向子组件传递数据的方式，而 state 用于管理组件内部状态。",
        "最后一段内容。React Hooks 是 React 16.8 引入的新特性，它让你在不编写 class 的情况下使用 state 和其他 React 特性。",
        "最后一段内容。React Hooks 是 React 16.8 引入的新特性，它让你在不编写 class 的情况下使用 state 和其他 React 特性。",
        "最后一段内容。React Hooks 是 React 16.8 引入的新特性，它让你在不编写 class 的情况下使用 state 和其他 React 特性。",
        "最后一段内容。React Hooks 是 React 16.8 引入的新特性，它让你在不编写 class 的情况下使用 state 和其他 React 特性。",
        "最后一段内容。React Hooks 是 React 16.8 引入的新特性，它让你在不编写 class 的情况下使用 state 和其他 React 特性。"
    ])


    const [visibleItems, setVisibleItems] = useState(5); // 初始加载数量
    const containerRef = useRef(null);
    const loadingRef = useRef(false);

    // 懒加载逻辑
    useEffect(() => {
        const container = containerRef.current;
        if (!container) return;

        const handleScroll = () => {
            if (
                !loadingRef.current &&
                container.scrollHeight - container.scrollTop <= container.clientHeight + 100
            ) {
                loadingRef.current = true;
                setVisibleItems(prev => Math.min(prev + 10, abc.length));
                setTimeout(() => { loadingRef.current = false }, 300);
            }
        };
        container.addEventListener('scroll', handleScroll);
        return () => container.removeEventListener('scroll', handleScroll);
    }, [abc.length]);
    console.log("fileNames:", fileNames, Array.isArray(fileNames)); // 检查是否是数组
    const extensions = useMemo(() => {
        return fileNames.map((fileName) => {
            // 分割文件名，取最后一部分作为扩展名
            const parts = fileName.split('.');
            return parts.length > 1 ? parts.pop() : 'txt'; // 如果没有扩展名，默认 'txt'
        });
    }, [fileNames])
    return (
        <div className="relative">
            {/* 下拉框 - 右上角 */}
            <div className="absolute -top-8 right-4 z-10">
                <Select defaultValue={fileNames[0]}>
                    <SelectTrigger className="w-[300px] h-[28px]">
                        <SelectValue placeholder="Select a file"/>
                    </SelectTrigger>
                    <SelectContent>
                        <SelectGroup>
                            {fileNames.map((fileName, index) => (
                                <SelectItem key={fileName} value={fileName}>
                                    <div className="flex items-center gap-2">
                                        <FileIcon type={extensions[index]} className="size-4" />
                                        {fileName}
                                    </div>
                                </SelectItem>
                            ))}
                        </SelectGroup>
                    </SelectContent>
                </Select>
            </div>

            {/* 其他内容 */}
            <div
                ref={containerRef}
                className="overflow-y-auto max-h-[80vh] w-full p-2 mt-16"
                style={{ scrollbarWidth: 'thin' }}
            >
                <div className="p-4">
                    <div className="space-y-6">
                        {abc.slice(0, visibleItems).map((text, index) => (
                            <div key={index} className="p-4 bg-white rounded-lg shadow-sm border border-gray-200 hover:shadow-md transition-shadow w-full">
                                <div className="flex items-start">
                                    <p className="text-gray-700 leading-relaxed whitespace-pre-wrap break-words w-full">
                                        {text}
                                    </p>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            </div>
        </div>
    )
}
