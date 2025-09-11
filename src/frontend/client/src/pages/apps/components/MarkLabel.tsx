




import { CircleX, LightbulbIcon } from 'lucide-react';
import { useEffect, useState } from 'react';
import { DragDropContext, Draggable, Droppable } from 'react-beautiful-dnd';
import { getAllLabelsApi, updateHomeLabelApi } from '~/api/apps';
import { Button, Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "~/components";
import { useToastContext } from "~/Providers";
import { cn } from "~/utils";

function DragItem({ className = '', data, children, onCancel }) {
    return <div className={cn('h-7 w-32 relative rounded-md rounded-l-xl border flex place-items-center', className)}>
        <CircleX onClick={(e) => { e.stopPropagation(); onCancel(data.id) }}
            className='text-gray-400 absolute top-[-6px] right-[-6px] cursor-pointer size-4' />
        <div className='bg-gray-500 rounded-full w-[26px] h-full text-center'>
            <span className='text-slate-50 font-bold text-sm'>{data.index}</span>
        </div>
        <div className='ml-2 truncate'>
            {children}
        </div>
    </div>
}

export default function MarkLabel({ open, home, onClose }) {
    const [labels, setLabels] = useState([])
    const [selected, setSelected] = useState([])

    const { showToast } = useToastContext();

    useEffect(() => {
        async function init() {
            const all = await getAllLabelsApi()
            const newData = all.data.data.map(d => {
                const res = home.find(h => h.value === d.id)
                return res ? { label: d.name, value: d.id, selected: true } : { label: d.name, value: d.id, selected: false }
            })
            setLabels(newData)
            setSelected(home)
        }
        init()
    }, [home])

    const handleCancel = () => {
        onClose(false)
    }

    const handleConfirm = async () => {
        await updateHomeLabelApi(selected.map(s => s.value))
        // TODO 重新加载列表
        onClose(true)
    }

    const handleSelect = (id) => {
        setLabels(pre => {
            const newData = pre.map(l => l.value === id ? { ...l, selected: !l.selected } : l)
            if (newData.filter(d => d.selected).length > 10) {
                showToast({ message: '最多选择10个标签', status: 'warning' });
                return pre
            }
            const select = newData.find(d => d.value === id && d.selected)
            setSelected(select ? [...selected, select] : pre => pre.filter(d => d.value !== id))
            return newData
        })
    }

    const handleDelete = (id) => {
        setSelected(pre => pre.filter(d => d.value !== id))
        setLabels(pre => pre.map(d => d.value === id ? { ...d, selected: !d.selected } : d))
    }

    const handleDragEnd = (result) => {
        if (!result.destination) return
        const newData = selected
        const [moveItem] = newData.splice(result.source.index, 1)
        newData.splice(result.destination.index, 0, moveItem)
        setSelected(newData)
        setFlag(false)
    }

    const [flag, setFlag] = useState(false) // 解决拖拽映射位置错位

    return <Dialog open={open} onOpenChange={onClose}>
        <DialogContent className='max-w-[70%] overflow-hidden'>
            <DialogHeader className='h-20'>
                <DialogTitle className='flex items-center space-x-2'>
                    <LightbulbIcon />
                    <span className='text-sm text-gray-500'>操作提示：在左侧选择要展示的标签，在右侧拖拽进行排序</span>
                </DialogTitle>
            </DialogHeader>
            <div className='h-[600px] w-full grid grid-cols-[70%_30%]'>
                <div className='ml-10'>
                    <div className='w-full relative'>
                        {
                            labels.map(l =>
                                <Button onClick={() => handleSelect(l.value)}
                                    size='sm'
                                    className={`ml-4 mt-4 p-1 ${!l.selected && 'bg-primary/40 hover:bg-primary/70'} w-[120px]`}>
                                    <span className='truncate text-xs'>{l.label}</span>
                                </Button>)
                        }
                    </div>
                </div>
                <div className='border-l text-gray-500'>
                    <div className='ml-4'>
                        <span className='text-md font-bold'>已选：{selected.length}/10</span>
                        <DragDropContext onDragEnd={handleDragEnd} onDragStart={() => setFlag(true)} onDragUpdate={() => setFlag(true)}>
                            <Droppable droppableId={'list'}>
                                {(provided) => (
                                    <div {...provided.droppableProps} ref={provided.innerRef}>
                                        {selected.map((b, index) => (
                                            <Draggable key={'drag' + b.value} draggableId={'drag' + b.value} index={index}>
                                                {(provided) => (
                                                    <div ref={provided.innerRef} {...provided.draggableProps} {...provided.dragHandleProps}
                                                        style={flag ? { ...provided.draggableProps.style, position: 'relative', left: 0, top: 0 } : { ...provided.draggableProps.style }}>
                                                        <DragItem onCancel={handleDelete} data={{ index: index + 1, id: b.value }} className='mt-4 w-[170px]'>
                                                            <span className='font-bold text-sm'>{b.label}</span>
                                                        </DragItem>
                                                    </div>
                                                )}
                                            </Draggable>
                                        ))}
                                        {provided.placeholder}
                                    </div>
                                )}
                            </Droppable>
                        </DragDropContext>
                    </div>
                </div>
            </div>
            <DialogFooter className='absolute bottom-6 right-6'>
                <Button variant="outline" className="h-10 w-[120px] px-16" onClick={handleCancel}>取消</Button>
                <Button className="px-16 h-10 w-[120px]" onClick={handleConfirm}>保存</Button>
            </DialogFooter>
        </DialogContent>
    </Dialog>
}