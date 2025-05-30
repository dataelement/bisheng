import { RbDragIcon } from '@/components/bs-icons/rbDrag';
import { NodeToolbar, useViewport } from '@xyflow/react';
import { useEffect, useRef, useState } from 'react';
import NodeToolbarComponent from './FlowNode/NodeToolbarComponent';
import { useHoverToolbar } from './FlowNode';

function NoteNode({ data: node, selected, width, height }: { data: any; selected: boolean, width: number, height: number }) {
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const { zoom } = useViewport();

    const [value, setValue] = useState(node.value);
    const [dimensions, setDimensions] = useState({ width, height });

    const [isDragging, setIsDragging] = useState(false);
    const [dragStart, setDragStart] = useState({ x: 0, y: 0, w: 0, h: 0 });

    // 自动调整高度
    const autoHeight = (textarea) => {
        if (!textarea) return;

        // 重置高度后获取自然高度
        textarea.style.height = 'auto';
        // 设置textarea实际高度
        textarea.style.height = `${textarea.scrollHeight}px`;
    }
    useEffect(() => {
        autoHeight(textareaRef.current);
    }, [node.value, dimensions.height]);

    // 拖拽处理
    const handleMouseDown = (e: React.MouseEvent) => {
        e.preventDefault();
        const parent = textareaRef.current?.parentElement;
        if (!parent) return;

        setDragStart({
            x: e.clientX,
            y: e.clientY,
            w: parent.offsetWidth,
            h: parent.offsetHeight,
        });
        setIsDragging(true);
    };

    useEffect(() => {
        const handleMouseMove = (e: MouseEvent) => {
            if (!isDragging) return;

            const deltaX = (e.clientX - dragStart.x) / zoom;
            const deltaY = (e.clientY - dragStart.y) / zoom;

            setDimensions({
                width: dragStart.w + deltaX,
                height: dragStart.h + deltaY
            });
        };

        const handleMouseUp = () => {
            setIsDragging(false)
        };

        if (isDragging) {
            document.addEventListener('mousemove', handleMouseMove);
            document.addEventListener('mouseup', handleMouseUp);
        }

        return () => {
            document.removeEventListener('mousemove', handleMouseMove);
            document.removeEventListener('mouseup', handleMouseUp);
        };
    }, [isDragging, dragStart]);

    const { isVisible, handleMouseEnter, handleMouseLeave } = useHoverToolbar();
    return (
        <div
            className={`bisheng-node justify-start min-w-60 min-h-28 relative rounded-md border p-2 pt-4 bg-yellow-50 hover:border-orange-300 ${selected ? 'border-orange-300' : 'border-transparent'
                }`}
            data-id={node.id}
            style={{
                width: dimensions.width,
                height: dimensions.height,
            }}
            onMouseEnter={handleMouseEnter}
            onMouseLeave={handleMouseLeave}
        >
            <NodeToolbar isVisible align="end" className={`${isVisible ? '' : 'hidden'}`} >
                <NodeToolbarComponent nodeId={node.id} type={node.type} onRun={() => { }} ></NodeToolbarComponent>
            </NodeToolbar>
            <textarea
                ref={textareaRef}
                className="nodrag nowheel w-full resize-none bg-transparent border-none  outline-none text-sm text-[#111] placeholder-gray-400 nodrag"
                placeholder="留下您的想法～"
                value={value}
                maxLength={5000}
                onInput={() => {
                    const _value = textareaRef.current?.value || ''
                    node.value = _value;
                    setValue(_value);
                    autoHeight(textareaRef.current);
                }}
            />

            {/* 拖拽手柄 */}
            <div
                className="nodrag absolute bottom-0 right-0 w-4 h-4 cursor-se-resize text-transparent"
                onMouseDown={handleMouseDown}
            ><RbDragIcon /></div>
        </div>
    );
}

export default NoteNode;