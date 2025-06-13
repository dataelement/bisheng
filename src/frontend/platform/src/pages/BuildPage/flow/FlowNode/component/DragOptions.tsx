import { Button } from '@/components/bs-ui/button';
import { Input } from '@/components/bs-ui/input';
import { generateUUID } from '@/components/bs-ui/utils';
import { Handle, Position } from '@xyflow/react';
import i18next from "i18next";
import { Edit, GripVertical, Trash2 } from 'lucide-react'; // 图标
import { forwardRef, useEffect, useRef, useState } from 'react';
import { DragDropContext, Draggable, Droppable } from 'react-beautiful-dnd';
import { useTranslation } from 'react-i18next';

interface Iprops {
    edges?: boolean,
    edit?: boolean,
    options: {
        id: string;
        text: string;
        type: string;
    }[],
    scroll?: boolean,
    onEditClick?: (index: number, option: Iprops["options"][0]) => void
    onChange?: (options: Iprops["options"]) => void
};

// TODO 移动到业务组件
const itemNames = {
    'select': i18next.t('dropdown', { ns: 'flow' }),
    'file': i18next.t('file', { ns: 'flow' }),
    'text': i18next.t('dropdown', { ns: 'flow' })
}

const DragOptions = forwardRef(({ edges = false, edit = false, scroll = false, options, onEditClick, onChange }: Iprops, ref) => {
    const { t } = useTranslation('flow'); // 使用国际化
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

    const handleBeforAddItem = () => {
        if (items.length >= 30) {
            setError(t('maxOptionsError')); // 使用国际化文本
            return;
        }
        setIsAdding(true);
    }

    const handleAddItem = () => {
        if (!inputValue.trim()) {
            setError(t('emptyOptionError')); // 使用国际化文本
            return;
        }

        // 检查重复内容
        const isDuplicate = items.some(item => item.text === inputValue.trim());
        if (isDuplicate) {
            setError(t('duplicateOptionError')); // 使用国际化文本
            return;
        }

        if (inputValue.length > 50) {
            setError(t('lengthOptionError')); // 使用国际化文本
            return;
        }

        const newItem = {
            id: generateUUID(8),
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
        <div ref={ref} className={`${scroll && 'nowheel overflow-y-auto max-h-80'} mt-2`}>
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
                                    {(provided) => (
                                        <div
                                            ref={provided.innerRef}
                                            {...provided.draggableProps}
                                            style={{ ...provided.draggableProps.style, position: 'relative', top: 0, left: 0 }}
                                            className="flex items-center gap-2 relative"
                                        >
                                            <div className='group w-full flex items-center rounded-md border border-input bg-search-input shadow-sm'>
                                                <div {...provided.dragHandleProps} className="flex flex-col justify-center border-r px-1">
                                                    <GripVertical size={20} color="#999" />
                                                </div>
                                                <Option
                                                    item={item}
                                                    count={items.length}
                                                    edit={edit}
                                                    onEditClick={() => onEditClick?.(index, item)}
                                                    onDelete={handleDelete}
                                                    onChange={(text) => updateItems(items.map((e, i) => i === index ? { ...e, text } : e))} />
                                            </div>
                                            {
                                                edges && <Handle
                                                    id={item.id}
                                                    type="source"
                                                    position={Position.Right}
                                                    className='bisheng-flow-handle group'
                                                    style={{ right: -30, top: 18 }}
                                                ><span></span></Handle>
                                            }
                                        </div>
                                    )}
                                </Draggable>
                            ))}
                        </div>
                    )}
                </Droppable>
            </DragDropContext>

            {!onEditClick && <div className="mt-4">
                {!isAdding ? (
                    <Button onClick={handleBeforAddItem} type='button' variant='outline' className="border-primary text-primary mt-2">
                        + {t('addOption')} {/* 添加选项 */}
                    </Button>
                ) : (
                    <div className="flex items-center space-x-2">
                        <Input
                            value={inputValue}
                            placeholder={t('inputOptionPlaceholder')} // 请输入选项展示文本
                            onChange={(e) => setInputValue(e.target.value)}
                            maxLength={50}
                            showCount
                        />
                        <Button type="button" onClick={handleAddItem} className="flex-none">
                            {t('confirm')} {/* 确定 */}
                        </Button>
                    </div>
                )}
                {error && <p className="text-red-500 mt-2 text-sm">{error}</p>}
            </div>}
        </div>
    );
});

export default DragOptions;


const Option = ({ item, count, edit, onEditClick, onDelete, onChange }) => {

    const [editing, setEditing] = useState(false);
    const inputRef = useRef(null);
    // const prevText = useRef('');

    const handleEdit = () => {
        if (edit) {
            setEditing(true);
        } else {
            onEditClick();
        }
    }

    const handleChange = () => {
        const val = inputRef.current.value
        setEditing(false)
        val && onChange(val)
    }

    return <>
        <div className="flex-1">
            {editing ?
                <Input
                    ref={inputRef}
                    autoFocus
                    className='border-none outline-none focus-visible:ring-transparent'
                    value={item.text}
                    onBlur={handleChange}
                    onKeyDown={(e) => e.key === 'Enter' && handleChange()}
                ></Input>
                : <div
                    className="h-9 leading-9 w-[200px] px-2 text-sm text-[#111] dark:text-gray-50 cursor-not-allowed opacity-50 truncate"
                >{item.text}</div>}
        </div>
        <div className='flex gap-1 items-center pr-2'>
            <span className='text-xs text-muted-foreground group-hover:hidden'>{itemNames[item.type] || item.type}</span>
            {(onEditClick || edit) && <Edit size={14} onClick={handleEdit} className='cursor-pointer text-muted-foreground hover:text-foreground hidden group-hover:block' />}
            {count > 1 && (
                <Trash2
                    size={14}
                    className="cursor-pointer text-gray-500 hover:text-red-500 transition-colors duration-200 hidden group-hover:block"
                    onClick={() => onDelete(item.text)}
                />
            )}
        </div>
    </>
}