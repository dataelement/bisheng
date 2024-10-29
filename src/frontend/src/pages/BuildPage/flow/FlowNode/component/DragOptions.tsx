import { Button } from '@/components/bs-ui/button';
import { Input } from '@/components/bs-ui/input';
import { generateUUID } from '@/components/bs-ui/utils';
import { Edit, GripVertical, Trash2 } from 'lucide-react'; // 图标
import { useEffect, useRef, useState } from 'react';
import { DragDropContext, Draggable, Droppable } from 'react-beautiful-dnd';
import { Handle, Position } from 'reactflow';

interface Iprops {
    edges?: boolean,
    options: {
        id: string;
        text: string;
        type: string;
    }[],
    onEditClick?: (index: number, option: Iprops["options"][0]) => void
    onChange?: (options: Iprops["options"]) => void
};

export default function DragOptions({ edges = false, options, onEditClick, onChange }: Iprops) {
    const [items, setItems] = useState([]); // 初始默认选项
    const [inputValue, setInputValue] = useState("");
    const [error, setError] = useState("");
    const [isAdding, setIsAdding] = useState(false); // 控制按钮和输入框切换

    // 当弹窗打开时，计算弹窗的上边和左边的偏移量
    useEffect(() => {
        setItems(options)
    }, [options]);

    // 更新父组件的 options 数组
    const updateItems = (newItems) => {
        setItems(newItems);
        if (onChange) {
            onChange(newItems); // 将新数组传递给父组件
        }
    };

    const handleAddItem = () => {
        if (items.length >= 30) {
            setError("最多添加 30 个选项");
            return;
        }

        if (!inputValue.trim()) {
            setError("选项内容不可为空");
            return;
        }

        // 检查重复内容
        const isDuplicate = items.some(item => item.text === inputValue.trim());
        if (isDuplicate) {
            setError("选项内容重复");
            return;
        }

        if (inputValue.length > 50) {
            setError("选项内容不能超过 50 个字符");
            return;
        }

        const newItem = {
            // key: 'xx',
            id: generateUUID(5),
            text: inputValue.trim(),
            type: ''
        };

        const newItems = [...items, newItem];
        updateItems(newItems); // 更新 items 并传递给父组件
        setInputValue("");
        setError("");
        setIsAdding(false); // 切换回按钮
    };

    const handleDelete = (text) => {
        const newItems = items.filter((item) => item.text !== text);
        updateItems(newItems); // 更新 items 并传递给父组件
    };

    const handleDragEnd = (result) => {
        if (!result.destination) return;
        const newItems = Array.from(items);
        const [removed] = newItems.splice(result.source.index, 1);
        newItems.splice(result.destination.index, 0, removed);
        updateItems(newItems); // 更新 items 并传递给父组件
    };

    return (
        <div className='mt-2'>
            <DragDropContext onDragEnd={handleDragEnd} usePortal>
                <Droppable droppableId="options-list">
                    {(provided) => (
                        <div
                            {...provided.droppableProps}
                            ref={provided.innerRef}
                            className="space-y-2"
                        >
                            {items.map((item, index) => (
                                <Draggable key={item.text} draggableId={item.text} index={index}>
                                    {(provided, snapshot) => (
                                        <div
                                            ref={provided.innerRef}
                                            {...provided.draggableProps}
                                            style={{ ...provided.draggableProps.style, position: 'relative', top: 0, left: 0 }}
                                            className="flex items-center gap-2 relative"
                                        >
                                            <div {...provided.dragHandleProps} className="flex flex-col justify-center">
                                                <GripVertical size={20} color="#999" />
                                            </div>
                                            <div className="flex-1 relative">
                                                <Input value={item.text} disabled className="cursor-default" />
                                                <span className='absolute top-2.5 right-2 text-xs text-muted-foreground'>{item.type}</span>
                                            </div>
                                            {onEditClick && <Edit size={20} onClick={() => onEditClick(index, item)} className='cursor-pointer text-muted-foreground hover:text-foreground' />}
                                            {items.length > 1 && (
                                                <Trash2
                                                    size={20}
                                                    className="cursor-pointer text-gray-500 hover:text-red-500 transition-colors duration-200"
                                                    onClick={() => handleDelete(item.text)}
                                                />
                                            )}
                                            {
                                                edges && <Handle
                                                    id={item.id}
                                                    type="source"
                                                    position={Position.Right}
                                                    className='bisheng-flow-handle'
                                                    style={{ right: -18, top: 12 }}
                                                />
                                            }
                                        </div>
                                    )}
                                </Draggable>
                            ))}
                            {/* {provided.placeholder} */}
                        </div>
                    )}
                </Droppable>
            </DragDropContext>

            {!onEditClick && <div className="mt-4">
                {!isAdding ? (
                    <Button onClick={() => setIsAdding(true)} variant='outline' className="w-full border-dashed">
                        + 添加选项
                    </Button>
                ) : (
                    <div className="flex items-center space-x-2">
                        <Input
                            value={inputValue}
                            placeholder="请输入选项文本"
                            onChange={(e) => setInputValue(e.target.value)}
                            maxLength={50}
                        />
                        <Button type="button" onClick={handleAddItem} className="flex-none">
                            确定
                        </Button>
                    </div>
                )}
                {error && <p className="text-red-500 mt-2 text-sm">{error}</p>}
            </div>}
        </div>
    );
}
