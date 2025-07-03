import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import Vditor from "vditor";
import "vditor/dist/index.css";
import SopToolsDown from "./SopToolsDown";

interface MarkdownProps {
    value?: string | null;
    tools?: any[]; // 根据实际情况调整类型
    isExecuting?: boolean;
}

interface MarkdownRef {
    getValue: () => { sop: string, sop_map: { [key in string]: string } };
}

const Markdown = forwardRef<MarkdownRef, MarkdownProps>((props, ref) => {
    const { value = '', tools, isExecuting } = props;

    const veditorRef = useRef<any>(null);
    const inserRef = useRef<any>(null);
    const boxRef = useRef<any>(null);
    useEffect(() => {
        const vditorDom = document.getElementById('vditor');
        if (!vditorDom) return

        const vditor = new Vditor("vditor", {
            value,
            cdn: location.origin + __APP_ENV__.BASE_URL + '/vditor',
            toolbar: [],
            cache: {
                enable: false
            },
            height: boxRef.current.clientHeight,
            mode: "wysiwyg",
            placeholder: "",
            after: () => {
                veditorRef.current = vditor;
            },
            hint: {
                parse: false, // 必须
                placeholder: {
                    delay: 2000,
                    text: "输入 @ 添加知识库、文件或工具",
                },
                extend: [{
                    key: '@',
                    callback(open, insert) {
                        const pos = vditor.getCursorPosition()
                        console.log('pos :>> ', open, pos);
                        setMenuPosition({ left: pos.left, top: pos.top + 28 });
                        setMenuOpen(open);

                        inserRef.current = insert;
                    }
                }]
            },
            preview: {
                delay: 500,
                markdown: {
                    toc: true,
                    mark: true,
                    footnotes: true,
                    autoSpace: true,
                },
                math: {
                    inlineDigit: true,
                }
            },
            tab: "\t",
        });

        return () => {
            veditorRef.current?.destroy();
            veditorRef.current = null
        };
    }, []);

    useEffect(() => {
        value ?? veditorRef.current?.setValue(value)
    }, [value])

    // 开启/禁用
    useEffect(() => {
        if (isExecuting) {
            veditorRef.current?.disabled()
        } else {
            veditorRef.current?.enable()
        }
    }, [isExecuting])

    // 暴露方法给父组件
    useImperativeHandle(ref, () => ({
        getValue: () => {
            return {
                sop: veditorRef.current?.getValue(),
                sop_map: sopMapRef.current
            }
        },
    }));

    const [menuOpen, setMenuOpen] = useState(false);
    const [menuPosition, setMenuPosition] = useState({ top: 0, left: 0 });

    // tools -> { label: "绘画工具", value: "painting-tools" }
    const toolsOptions = [
        {
            label: "绘画工具",
            children: [
                { label: "铅笔", value: "铅笔" },
                { label: "画笔", value: "brush" },
            ],
        },
        {
            label: "3D建模",
            value: "3d-modeling", // 一级菜单本身可选
            children: [
                { label: "Blender", value: "blender" },
                { label: "Maya", value: "maya" },
            ],
        },
        {
            label: "图像处理",
            value: "image-processing" // 没有子菜单的一级菜单
        },
    ];

    const sopMapRef = useRef({});
    const handleChange = (val) => {
        inserRef.current(`{{${val}}}`);
        sopMapRef.current[val] = 'idxxx';
        setMenuOpen(false)
    }

    return <div ref={boxRef} className="relative h-full">
        <div id="vditor" className="linsight-vditor border-none" />
        {/* 工具选择 */}
        <div>
            <SopToolsDown
                open={menuOpen}
                position={menuPosition}
                options={toolsOptions}
                onChange={handleChange}
                onClose={() => setMenuOpen(false)}
            />
        </div>
    </div >;
});


export default Markdown;